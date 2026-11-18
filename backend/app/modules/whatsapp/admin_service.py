"""WhatsApp management for admins: channel status, template catalogue, delivery failures, message log, opt-in list, and the
simulator (which drives the REAL webhook code path with a signed Cloud-API-shaped payload)."""
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.modules.drivers import service as drivers_service
from app.modules.drivers.models import Driver
from app.modules.whatsapp import processor, sender
from app.modules.whatsapp.models import (
    APPROVAL_STATUSES, WhatsAppMessage, WhatsAppOptEvent, WhatsAppTemplate, WhatsAppWebhookEvent,
)
from app.modules.whatsapp.templates import _VAR


def _mask(value: str) -> str:
    return "••••" + value[-4:] if value else ""


async def status(db: AsyncSession) -> dict:
    s = get_settings()
    day_ago = datetime.now(UTC) - timedelta(hours=24)

    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar_one()

    last_in = (await db.execute(select(func.max(WhatsAppMessage.created_at)).where(WhatsAppMessage.direction == "in"))).scalar_one()
    last_out = (await db.execute(select(func.max(WhatsAppMessage.created_at)).where(WhatsAppMessage.direction == "out"))).scalar_one()
    tpl_total = await count(select(func.count()).select_from(WhatsAppTemplate))
    return {
        "configured": bool(s.whatsapp_access_token and s.whatsapp_phone_number_id), "mode": sender.mode(),
        "webhook_path": "/webhooks/whatsapp", "verify_token_set": bool(s.whatsapp_verify_token), "app_secret_set": bool(s.whatsapp_app_secret),
        "phone_number_id_masked": _mask(s.whatsapp_phone_number_id), "last_inbound_at": last_in, "last_outbound_at": last_out,
        "pending_events": await count(select(func.count()).select_from(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.status == "pending")),
        "failed_events": await count(select(func.count()).select_from(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.status == "failed")),
        "failed_deliveries_24h": await count(select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.delivery_status == "failed", WhatsAppMessage.direction == "out", WhatsAppMessage.created_at >= day_ago,
            or_(WhatsAppMessage.error.is_(None), ~WhatsAppMessage.error.like(f"{sender.SUPPRESSED}%")))),
        "templates": {"total": tpl_total,
                      "approved": await count(select(func.count()).select_from(WhatsAppTemplate).where(WhatsAppTemplate.approval_status == "approved")),
                      "needs_review": await count(select(func.count()).select_from(WhatsAppTemplate).where(WhatsAppTemplate.needs_native_review.is_(True)))},
    }


# ---------------------------------------------------------------- templates
def template_out(t: WhatsAppTemplate) -> dict:
    return {"id": t.id, "name": t.name, "language": t.language, "category": t.category, "body": t.body, "variables": t.variables,
            "buttons": t.buttons, "approval_status": t.approval_status, "needs_native_review": t.needs_native_review,
            "meta_template_id": t.meta_template_id, "updated_at": t.updated_at}


async def list_templates(db: AsyncSession, language: str | None, name: str | None) -> list[dict]:
    stmt = select(WhatsAppTemplate)
    if language:
        stmt = stmt.where(WhatsAppTemplate.language == language)
    if name:
        stmt = stmt.where(WhatsAppTemplate.name == name)
    return [template_out(t) for t in (await db.execute(stmt.order_by(WhatsAppTemplate.name, WhatsAppTemplate.language))).scalars().all()]


def _validate_body(body: str, variables: list[str] | None) -> list[str]:
    found = sorted(set(_VAR.findall(body)))
    return variables if variables is not None else found


async def create_template(db: AsyncSession, data: dict) -> dict:
    if (await db.execute(select(WhatsAppTemplate.id).where(WhatsAppTemplate.name == data["name"], WhatsAppTemplate.language == data["language"]))).first():
        raise ConflictError("TEMPLATE_EXISTS", "A template with this name and language already exists")
    t = WhatsAppTemplate(name=data["name"], language=data["language"], category=data.get("category") or "UTILITY", body=data["body"],
                         variables=_validate_body(data["body"], data.get("variables")), buttons=data.get("buttons") or [],
                         approval_status="draft", needs_native_review=data["language"] != "en")
    db.add(t)
    await db.flush()
    return template_out(t)


async def update_template(db: AsyncSession, template_id: UUID, data: dict) -> dict:
    t = await db.get(WhatsAppTemplate, template_id)
    if t is None:
        raise NotFoundError("Template not found")
    if "approval_status" in data and data["approval_status"] not in APPROVAL_STATUSES:
        raise ValidationAppError("approval_status must be one of " + ", ".join(APPROVAL_STATUSES))
    for k in ("body", "approval_status", "needs_native_review", "buttons"):
        if k in data and data[k] is not None:
            setattr(t, k, data[k])
    if data.get("body"):
        t.variables = _validate_body(t.body, None)
    return template_out(t)


# ---------------------------------------------------------------- failures, log, opt-ins
async def _driver_names(db: AsyncSession, rows: list[WhatsAppMessage]) -> dict:
    return await drivers_service.names(db, list({r.driver_id for r in rows if r.driver_id}))


def message_out(r: WhatsAppMessage, names: dict | None = None) -> dict:
    raw = r.raw or {}
    return {"id": r.id, "wa_message_id": r.wa_message_id, "direction": r.direction, "driver_id": r.driver_id,
            "driver_name": (names or {}).get(r.driver_id), "thread_id": r.thread_id, "to_number": r.to_number, "type": r.type, "text": r.text,
            "language": r.language, "template_name": r.template_name, "delivery_status": r.delivery_status, "error": r.error,
            "purpose": r.purpose, "attempts": r.attempts, "created_at": r.created_at,
            "buttons": raw.get("buttons") or [], "rows": raw.get("rows") or [], "list_button": raw.get("list_button")}


async def failures(db: AsyncSession, limit: int, offset: int) -> dict:
    stmt = select(WhatsAppMessage).where(WhatsAppMessage.direction == "out", WhatsAppMessage.delivery_status == "failed",
                                         or_(WhatsAppMessage.error.is_(None), ~WhatsAppMessage.error.like(f"{sender.SUPPRESSED}%")))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(WhatsAppMessage.created_at.desc()).limit(limit).offset(offset))).scalars().all())
    names = await _driver_names(db, rows)
    return {"total": total, "items": [message_out(r, names) for r in rows]}


async def messages(db: AsyncSession, driver_id, thread_id, direction, status_, q, limit: int, offset: int) -> dict:
    stmt = select(WhatsAppMessage)
    for col, val in ((WhatsAppMessage.driver_id, driver_id), (WhatsAppMessage.thread_id, thread_id), (WhatsAppMessage.direction, direction),
                     (WhatsAppMessage.delivery_status, status_)):
        if val is not None:
            stmt = stmt.where(col == val)
    if q:
        stmt = stmt.where(WhatsAppMessage.text.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list((await db.execute(stmt.order_by(WhatsAppMessage.created_at.desc()).limit(limit).offset(offset))).scalars().all())
    return {"total": total, "items": [message_out(r, await _driver_names(db, rows)) for r in rows]}


async def opt_ins(db: AsyncSession, state: str | None, limit: int, offset: int) -> dict:
    flag = {"opted_in": True, "opted_out": False}.get(state or "")
    if state and flag is None:
        raise ValidationAppError("state must be opted_in or opted_out")
    total, drivers = await drivers_service.list_by_opt_state(db, flag, limit, offset)
    last: dict = {}
    if drivers:
        for e in (await db.execute(select(WhatsAppOptEvent).where(WhatsAppOptEvent.driver_id.in_([d.id for d in drivers]))
                                   .order_by(WhatsAppOptEvent.created_at))).scalars().all():
            last[e.driver_id] = {"event": e.event, "source": e.source, "at": e.created_at}
    return {"total": total, "items": [{"driver_id": d.id, "code": d.code, "name": d.driver_name, "whatsapp_number": d.whatsapp_number,
                                       "preferred_language": d.preferred_language, "verified": d.verified_at is not None,
                                       "opted_in": d.whatsapp_opt_in, "last_event": last.get(d.id)} for d in drivers]}


async def set_opt_in(db: AsyncSession, driver_id: UUID, opted_in: bool) -> dict:
    d = await drivers_service.set_opt_in(db, driver_id, opted_in)
    if d is None:
        raise NotFoundError("Driver not found")
    db.add(WhatsAppOptEvent(driver_id=driver_id, event="opt_in" if opted_in else "opt_out", source="admin_override"))
    await db.flush()
    return {"driver_id": d.id, "opted_in": d.whatsapp_opt_in}


# ---------------------------------------------------------------- simulator
def _simulator_allowed() -> None:
    if sender.mode() != "simulator" and get_settings().env == "production":
        raise ForbiddenError("The simulator is disabled when a live WhatsApp number is connected in production")


def build_payload(number: str, kind: str, *, text: str | None, button_id: str | None, list_id: str | None, title: str | None,
                  name: str | None) -> tuple[dict, str]:
    digits = sender.digits(number)
    wamid = f"wamid.SIMIN{uuid.uuid4().hex[:20]}"
    msg: dict = {"from": digits, "id": wamid, "timestamp": str(int(time.time()))}
    if kind == "text":
        msg.update(type="text", text={"body": text or ""})
    elif kind == "button":
        msg.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": button_id or "", "title": title or button_id or ""}})
    else:
        msg.update(type="interactive", interactive={"type": "list_reply", "list_reply": {"id": list_id or "", "title": title or list_id or ""}})
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "SIMULATOR", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "SetuHaul simulator", "phone_number_id": "simulator"},
        "contacts": [{"profile": {"name": name or "Driver"}, "wa_id": digits}], "messages": [msg]}}]}]}
    return payload, wamid


async def simulator_send(db: AsyncSession, body: dict) -> dict:
    _simulator_allowed()
    kind = body.get("kind", "text")
    if kind not in ("text", "button", "list"):
        raise ValidationAppError("kind must be text, button or list")
    driver = await db.get(Driver, body["driver_id"]) if body.get("driver_id") else None
    number = (driver.whatsapp_number if driver else None) or body.get("number")
    if not number:
        raise ValidationAppError("Give a driver_id with a WhatsApp number, or a number")
    if driver is None:
        driver = await drivers_service.find_by_whatsapp(db, number)
    if kind == "text" and not (body.get("text") or "").strip():
        raise ValidationAppError("text is required")
    payload, wamid = build_payload(number, kind, text=body.get("text"), button_id=body.get("button_id"), list_id=body.get("list_id"),
                                   title=body.get("title"), name=driver.driver_name if driver else None)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    secret = get_settings().whatsapp_app_secret
    if not secret:
        raise WebhookUnconfigured()
    start = datetime.now(UTC)
    ev = await processor.ingest(db, raw, processor.sign(raw, secret))  # the same code path as the real webhook
    await db.commit()
    await processor.process_event(db, ev.id)
    q = select(WhatsAppMessage).where(WhatsAppMessage.direction == "out", WhatsAppMessage.created_at >= start)
    q = q.where(WhatsAppMessage.driver_id == driver.id) if driver else q.where(WhatsAppMessage.to_number == processor.normalise_number(number))
    replies = list((await db.execute(q.order_by(WhatsAppMessage.created_at))).scalars().all())
    names = await _driver_names(db, replies)
    inbound = (await db.execute(select(WhatsAppMessage.id).where(WhatsAppMessage.wa_message_id == wamid))).scalar_one_or_none()
    return {"event_id": ev.id, "inbound_message_id": inbound, "replies": [message_out(r, names) for r in replies]}


class WebhookUnconfigured(ValidationAppError):
    def __init__(self) -> None:
        super().__init__("Set WHATSAPP_APP_SECRET so the simulator can sign its payloads like Meta does")


async def conversation(db: AsyncSession, driver_id: UUID, limit: int) -> list[dict]:
    rows = list((await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.driver_id == driver_id)
                                  .order_by(WhatsAppMessage.created_at.desc()).limit(limit))).scalars().all())
    rows.reverse()
    names = await _driver_names(db, rows)
    return [message_out(r, names) for r in rows]


async def reset(db: AsyncSession, driver_id: UUID) -> int:
    _simulator_allowed()
    if sender.mode() != "simulator":
        raise ForbiddenError("Reset only works against the simulator")
    res = await db.execute(delete(WhatsAppMessage).where(WhatsAppMessage.driver_id == driver_id))
    return res.rowcount or 0


_ = re
