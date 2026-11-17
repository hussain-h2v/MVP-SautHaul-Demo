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


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    functions = [sweep_job]
    cron_jobs = [cron(sweep_job, second={0}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
