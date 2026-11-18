"""Outbound WhatsApp. One entry point, `send_message`, applies every policy before anything leaves the system:
never to an opted-out driver (except the single opt-out confirmation), never to an unverified number (except the
verification flow), free-form text/interactive only inside the 24-hour customer-service window (otherwise only an
approved template). Delivery goes through the Cloud API when configured, else the simulator sink. A failed message is
recorded as failed, alerts coordinators, and is never treated as a confirmation by anything."""
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import get_settings
from app.core.idempotency import get_redis
from app.core.outbox import emit
from app.core.security import decrypt_secret, encrypt_secret
from app.modules.drivers.models import Driver
from app.modules.whatsapp.models import ChatMessage, WhatsAppMessage
from app.modules.whatsapp.outbound import OutboundMessage
from app.modules.whatsapp.templates import Rendered

WINDOW = timedelta(hours=24)
MAX_ATTEMPTS = 5
CLOUD_MPS = 80  # Meta's default messages-per-second ceiling per number
SUPPRESSED = "SUPPRESSED:"

# tests inject an httpx transport here to assert the exact Cloud API requests
http_transport: httpx.AsyncBaseTransport | None = None


class SendError(Exception):
    def __init__(self, code: str, retryable: bool = False, detail: str = "") -> None:
        self.code, self.retryable, self.detail = code, retryable, detail
        super().__init__(f"{code}: {detail}")


def mode() -> str:
    s = get_settings()
    return "cloud" if (s.whatsapp_access_token and s.whatsapp_phone_number_id) else "simulator"


def digits(number: str) -> str:
    return "".join(c for c in number if c.isdigit())


# ---------------------------------------------------------------- Cloud API payloads (pure)
def text_payload(to: str, text: str) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": digits(to), "type": "text",
            "text": {"body": text, "preview_url": False}}


def buttons_payload(to: str, m: OutboundMessage) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": digits(to), "type": "interactive",
            "interactive": {"type": "button", "body": {"text": m.text},
                            "action": {"buttons": [{"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in m.buttons]}}}


def list_payload(to: str, m: OutboundMessage) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": digits(to), "type": "interactive",
            "interactive": {"type": "list", "body": {"text": m.text},
                            "action": {"button": (m.list_button or "Choose")[:20],
                                       "sections": [{"title": "Options", "rows": [
                                           {"id": r.id, "title": r.title, **({"description": r.description} if r.description else {})}
                                           for r in m.rows]}]}}}


def template_payload(to: str, t: Rendered) -> dict:
    components: list[dict] = []
    if t.variable_order:
        components.append({"type": "body", "parameters": [{"type": "text", "text": str(t.variables.get(v, ""))} for v in t.variable_order]})
    for i, b in enumerate(t.buttons):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(i), "parameters": [{"type": "payload", "payload": b.id}]})
    return {"messaging_product": "whatsapp", "to": digits(to), "type": "template",
            "template": {"name": t.name, "language": {"code": t.language}, "components": components}}


def payload_for(to: str, message: OutboundMessage | None, template: Rendered | None) -> dict:
    if template is not None:
        return template_payload(to, template)
    assert message is not None
    if message.kind == "buttons":
        return buttons_payload(to, message)
    if message.kind == "list":
        return list_payload(to, message)
    return text_payload(to, message.text)


# ---------------------------------------------------------------- transports
async def cloud_send(payload: dict) -> str:
    s = get_settings()
    url = f"{s.whatsapp_graph_url.rstrip('/')}/{s.whatsapp_phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(transport=http_transport, timeout=15.0) as c:
            r = await c.post(url, json=payload, headers={"Authorization": f"Bearer {s.whatsapp_access_token}"})
    except httpx.TimeoutException as e:
        raise SendError("TIMEOUT", True, str(e)) from e
    except httpx.HTTPError as e:
        raise SendError("NETWORK", True, str(e)) from e
    if r.status_code == 200:
        try:
            return r.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError) as e:
            raise SendError("BAD_RESPONSE", True, r.text[:200]) from e
    body = {}
    try:
        body = r.json().get("error", {})
    except ValueError:
        pass
    code, detail = body.get("code"), (body.get("message") or r.text)[:200]
    if r.status_code in (401, 403) or code in (190, 10):
        raise SendError("AUTH_ERROR", False, detail)
    if code == 131047:  # re-engagement message: outside the customer-service window
        raise SendError("WINDOW_CLOSED", False, detail)
    if r.status_code == 429 or code in (4, 80007, 130429):
        raise SendError("RATE_LIMITED", True, detail)
    if r.status_code >= 500:
        raise SendError("SERVER_ERROR", True, detail)
    raise SendError("BAD_REQUEST", False, detail)


async def simulator_send(payload: dict) -> str:
    return f"wamid.SIM{uuid.uuid4().hex[:20]}"


# ---------------------------------------------------------------- window and policy
async def last_inbound_at(db: AsyncSession, driver_id) -> datetime | None:
    return (await db.execute(select(WhatsAppMessage.created_at).where(WhatsAppMessage.driver_id == driver_id, WhatsAppMessage.direction == "in")
                             .order_by(WhatsAppMessage.created_at.desc()).limit(1))).scalar_one_or_none()


async def window_open(db: AsyncSession, driver_id, now: datetime) -> bool:
    last = await last_inbound_at(db, driver_id)
    return last is not None and now - last < WINDOW


def _mask_text(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "•" * len(s))
    return text


async def record_failure(db: AsyncSession, row: WhatsAppMessage, error: str, *, alert: bool = True) -> None:
    row.delivery_status, row.error, row.next_attempt_at = "failed", error[:500], None
    if error.startswith(SUPPRESSED) or not alert:
        return
    from app.modules.drivers import service as drivers_service
    from app.modules.notifications import service as notifications_service
    from app.modules.shipments import service as shipments_service

    driver_name = None
    if row.driver_id:
        driver_name = (await drivers_service.names(db, [row.driver_id])).get(row.driver_id)
        active = await shipments_service.active_for_driver(db, row.driver_id)
        if active:
            await notifications_service.record_failed_whatsapp(db, active[0].id, row.to_number or "", row.text or row.template_name or "")
    emit(db, "whatsapp.delivery_failed", {
        "title": f"WhatsApp message to {driver_name or row.to_number or 'a driver'} failed",
        "body": f"{error} ({row.template_name or row.purpose or 'message'})", "message_id": row.id, "driver_id": row.driver_id,
        "error": error, "purpose": row.purpose, "template": row.template_name})


async def _rate_limited() -> bool:
    r = get_redis()
    try:
        key = f"wa:send:{int(time.time())}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 3)
        return n > CLOUD_MPS
    except Exception:
        return False
    finally:
        await r.aclose()


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** attempts * 5, 600))


async def deliver(db: AsyncSession, row: WhatsAppMessage, payload: dict, now: datetime | None = None) -> WhatsAppMessage:
    """One delivery attempt. Transient failures stay queued with exponential backoff (the worker retries them)."""
    now = now or datetime.now(UTC)
    cloud = mode() == "cloud"
    if cloud and await _rate_limited():
        row.next_attempt_at = now + timedelta(seconds=1)
        return row
    row.attempts += 1
    try:
        wa_id = await (cloud_send(payload) if cloud else simulator_send(payload))
    except SendError as e:
        if e.retryable and row.attempts < MAX_ATTEMPTS:
            row.error, row.next_attempt_at = e.code, now + _backoff(row.attempts)
            return row
        await record_failure(db, row, e.code if not e.detail else f"{e.code}: {e.detail}")
        return row
    row.wa_message_id, row.error, row.next_attempt_at = wa_id, None, None
    row.delivery_status = "sent" if cloud else "delivered"
    if not cloud:
        try:
            await events.publish("whatsapp.simulator", {"driver_id": str(row.driver_id) if row.driver_id else None, "message_id": str(row.id)})
        except Exception:
            pass
    return row


async def send_message(db: AsyncSession, *, driver: Driver | None, number: str | None = None, message: OutboundMessage | None = None,
                       template: Rendered | None = None, purpose: str, thread_id=None, chat_sender: str | None = None,
                       now: datetime | None = None, allow_opted_out: bool = False, allow_unverified: bool = False,
                       secrets: list[str] | None = None, language: str | None = None) -> WhatsAppMessage:
    """Create the outbound row, apply the policies, deliver. Always returns the row (check delivery_status / error)."""
    assert (message is None) != (template is None), "send exactly one of message / template"
    now = now or datetime.now(UTC)
    to = (driver.whatsapp_number if driver else None) or number
    text = template.body if template else message.text
    kind = "template" if template else ("interactive" if message.kind in ("buttons", "list") else "text")
    raw: dict = {}
    if message is not None:
        raw = {"kind": message.kind, "buttons": [{"id": b.id, "title": b.title} for b in message.buttons], "list_button": message.list_button,
               "rows": [{"id": r.id, "title": r.title, "description": r.description} for r in message.rows]}
    else:
        raw = {"buttons": [{"id": b.id, "title": b.title} for b in template.buttons]}
    row = WhatsAppMessage(
        direction="out", driver_id=driver.id if driver else None, thread_id=thread_id, to_number=to, type=kind,
        text=_mask_text(text, secrets or []), language=language or (template.language if template else (message.language if message else None)),
        template_name=template.name if template else None, delivery_status="queued", purpose=purpose or (message.purpose if message else None),
        raw=raw, attempts=0)
    db.add(row)
    await db.flush()
    if not to:
        await record_failure(db, row, "NO_NUMBER")
        return row
    if driver is not None and not driver.whatsapp_opt_in and not allow_opted_out:
        await record_failure(db, row, f"{SUPPRESSED}OPTED_OUT")
        return row
    if driver is not None and driver.verified_at is None and not allow_unverified:
        await record_failure(db, row, f"{SUPPRESSED}UNVERIFIED")
        return row
    if template is None and driver is not None and not await window_open(db, driver.id, now):
        await record_failure(db, row, "WINDOW_CLOSED")
        return row
    payload = payload_for(to, message, template)
    row.raw = {**raw, "payload_enc": encrypt_secret(json.dumps(payload))}  # encrypted: it may carry a verification code
    if chat_sender and thread_id is not None and message is not None:
        db.add(ChatMessage(code=f"WA{uuid.uuid4().hex[:12]}", thread_id=thread_id, sender_type=chat_sender, message_text=text[:4000],
                           message_ts=now, external_message_id=None))
    await db.flush()
    return await deliver(db, row, payload, now)


async def retry_due(db: AsyncSession, limit: int = 50, now: datetime | None = None) -> int:
    """Worker: re-attempt queued messages whose backoff has elapsed."""
    now = now or datetime.now(UTC)
    rows = (await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.direction == "out", WhatsAppMessage.delivery_status == "queued",
                                                           WhatsAppMessage.next_attempt_at.is_not(None), WhatsAppMessage.next_attempt_at <= now)
                             .order_by(WhatsAppMessage.next_attempt_at).limit(limit).with_for_update(skip_locked=True)
                             .execution_options(populate_existing=True))).scalars().all()
    n = 0
    for row in rows:
        enc = (row.raw or {}).get("payload_enc")
        if not enc:
            await record_failure(db, row, "NO_PAYLOAD")
            continue
        await deliver(db, row, json.loads(decrypt_secret(enc)), now)
        n += 1
    await db.flush()
    return n
