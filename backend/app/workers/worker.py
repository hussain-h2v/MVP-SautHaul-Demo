"""arq worker entrypoint. Recurring jobs are wired up in later milestones:
hold-expiry sweep, pending-confirmation expiry, no-show sweep, ETA staleness
check, nightly AI insight generation, and WhatsApp outbound delivery."""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings

settings = get_settings()


async def sweep_job(ctx: dict) -> dict:
    """Hold expiry, pending-confirmation expiry, no-show sweep, ETA staleness. Idempotent; safe to run twice."""
    from app.core import audit_events
    from app.core.db import async_session_factory
    from app.modules.booking import engine

    audit_events.install()
    async with async_session_factory() as db:
        counts = await engine.sweep(db)
        await db.commit()
        return counts


async def outbox_job(ctx: dict) -> dict:
    """Turns outbox events into in-app notifications and live events. Idempotent; locked rows are skipped."""
    from app.core.db import async_session_factory
    from app.modules.notifications import service

    async with async_session_factory() as db:
        res = await service.run_outbox(db)
        return {"sent": res.sent, "failed": res.failed, "notifications": res.notifications}


async def ai_log_retention_job(ctx: dict) -> dict:
    """Deletes AI usage logs older than system_settings.ai_log_retention_days. Idempotent."""
    from app.core.db import async_session_factory
    from app.modules.ai import usage

    async with async_session_factory() as db:
        n = await usage.delete_old_logs(db)
        await db.commit()
        return {"deleted": n}


async def process_whatsapp_event(ctx: dict, event_id: str) -> bool:
    """Processes one stored webhook event (enqueued by the webhook handler). Idempotent."""
    from uuid import UUID

    from app.core import audit_events
    from app.core.db import async_session_factory
    from app.modules.whatsapp import processor

    audit_events.install()
    async with async_session_factory() as db:
        return await processor.process_event(db, UUID(event_id))


async def whatsapp_event_job(ctx: dict) -> int:
    """Safety net: processes stored webhook events that were never enqueued or whose job was lost."""
    from app.core import audit_events
    from app.core.db import async_session_factory
    from app.modules.whatsapp import processor

    audit_events.install()
    async with async_session_factory() as db:
        return await processor.process_pending(db)


async def whatsapp_outbox_job(ctx: dict) -> dict:
    """Sends queued WhatsApp messages: outbox events (decisions, coordinator replies, verification codes) and backed-off retries."""
    from app.core import audit_events
    from app.core.db import async_session_factory
    from app.modules.whatsapp import dispatcher, sender

    audit_events.install()
    async with async_session_factory() as db:
        out = await dispatcher.process_outbox(db)
        out["retried"] = await sender.retry_due(db)
        await db.commit()
        return out


async def send_whatsapp(ctx: dict, message_id: str) -> bool:
    """Re-attempts one queued outbound message now (used by admin tools)."""
    import json
    from uuid import UUID

    from app.core.db import async_session_factory
    from app.core.security import decrypt_secret
    from app.modules.whatsapp import sender
    from app.modules.whatsapp.models import WhatsAppMessage

    async with async_session_factory() as db:
        row = await db.get(WhatsAppMessage, UUID(message_id))
        enc = (row.raw or {}).get("payload_enc") if row else None
        if row is None or row.delivery_status != "queued" or not enc:
            return False
        await sender.deliver(db, row, json.loads(decrypt_secret(enc)))
        await db.commit()
        return True


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    functions = [sweep_job, outbox_job, ai_log_retention_job, process_whatsapp_event, whatsapp_event_job, whatsapp_outbox_job, send_whatsapp]
    cron_jobs = [cron(sweep_job, second={0}, run_at_startup=False),
                 cron(outbox_job, second={0, 10, 20, 30, 40, 50}, run_at_startup=False),
                 cron(whatsapp_event_job, second={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57}, run_at_startup=False),
                 cron(whatsapp_outbox_job, second={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}, run_at_startup=False),
                 cron(ai_log_retention_job, hour={3}, minute={15}, second={0}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
