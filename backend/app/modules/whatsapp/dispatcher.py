"""Consumes the WhatsApp outbox events written by other modules in their own transactions:
whatsapp.template (coordinator decisions), whatsapp.send (coordinator replies), whatsapp.verification (driver number check).
Runs in the worker; locked rows are skipped so several workers never double-send. Failures back off and retry (max 5)."""
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.modules.drivers import service as drivers_service
from app.modules.notifications.models import OutboxEvent
from app.modules.notifications.service import MAX_ATTEMPTS, WHATSAPP_DELIVERY_EVENTS
from app.modules.whatsapp import sender
from app.modules.whatsapp.models import WhatsAppMessage
from app.modules.whatsapp.outbound import OutboundMessage
from app.modules.whatsapp.templates import render_template

log = logging.getLogger("whatsapp.dispatch")


async def _driver(db: AsyncSession, payload: dict):
    did = payload.get("driver_id")
    return (await drivers_service.get_many(db, [UUID(str(did))])).get(UUID(str(did))) if did else None


async def _no_template(db: AsyncSession, driver, name: str, lang: str) -> None:
    row = WhatsAppMessage(direction="out", driver_id=driver.id if driver else None, to_number=driver.whatsapp_number if driver else None,
                          type="template", text=f"[no approved template '{name}']", language=lang, template_name=name,
                          delivery_status="queued", purpose=name, attempts=0)
    db.add(row)
    await db.flush()
    await sender.record_failure(db, row, "NO_APPROVED_TEMPLATE")


async def dispatch(db: AsyncSession, ev: OutboxEvent, now: datetime) -> None:
    p = ev.payload or {}
    driver = await _driver(db, p)
    if driver is None:
        return  # nothing to send to (driver deleted): treat as done
    lang = p.get("language") or driver.preferred_language or "en"
    if ev.event_type == "whatsapp.template":
        name = p["template"]
        rendered = await render_template(db, name, lang, p.get("variables") or {})
        if rendered is None:
            await _no_template(db, driver, name, lang)
            return
        await sender.send_message(db, driver=driver, template=rendered, purpose=name, now=now, language=rendered.language)
    elif ev.event_type == "whatsapp.verification":
        code = decrypt_secret(p["code_enc"])
        rendered = await render_template(db, "verification", lang, {"code": code})
        if rendered is None:
            await _no_template(db, driver, "verification", lang)
            return
        # the verification message is how an unverified, not-yet-opted-in number proves it is the driver's
        await sender.send_message(db, driver=driver, template=rendered, purpose="verification", now=now, allow_opted_out=True,
                                  allow_unverified=True, secrets=[code], language=rendered.language)
    elif ev.event_type == "whatsapp.send":
        msg = OutboundMessage(kind="text", text=str(p["text"])[:4000], language=lang, purpose="coordinator_reply")
        thread_id = UUID(str(p["thread_id"])) if p.get("thread_id") else None
        await sender.send_message(db, driver=driver, message=msg, purpose="coordinator_reply", thread_id=thread_id, now=now, language=lang)


async def process_outbox(db: AsyncSession, limit: int = 50, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = (await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.event_type.in_(WHATSAPP_DELIVERY_EVENTS),
            or_(OutboxEvent.status == "pending", (OutboxEvent.status == "failed") & (OutboxEvent.attempts < MAX_ATTEMPTS)),
            or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now))
        .order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True).execution_options(populate_existing=True)
    )).scalars().all()
    sent = failed = 0
    for ev in rows:
        try:
            async with db.begin_nested():
                await dispatch(db, ev, now)
            ev.status, ev.attempts, ev.next_attempt_at = "sent", ev.attempts + 1, None
            sent += 1
        except Exception:  # noqa: BLE001
            log.exception("whatsapp outbox event failed", extra={"event_id": str(ev.id)})
            ev.status, ev.attempts = "failed", ev.attempts + 1
            ev.next_attempt_at = now + timedelta(seconds=min(2 ** ev.attempts * 5, 600))
            failed += 1
    await db.flush()
    return {"sent": sent, "failed": failed}
