"""arq worker entrypoint. Recurring jobs are wired up in later milestones:
hold-expiry sweep, pending-confirmation expiry, no-show sweep, ETA staleness
check, nightly AI insight generation, and WhatsApp outbound delivery."""

from arq.connections import RedisSettings

from app.core.config import get_settings

settings = get_settings()


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    functions: list = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
