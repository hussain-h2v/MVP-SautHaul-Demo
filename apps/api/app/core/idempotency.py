import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


async def get_cached_response(redis: Redis, key: str) -> dict[str, Any] | None:
    raw = await redis.get(f"idempotency:{key}")
    return json.loads(raw) if raw else None


async def cache_response(redis: Redis, key: str, status_code: int, body: Any) -> None:
    payload = json.dumps({"status_code": status_code, "body": body})
    await redis.set(f"idempotency:{key}", payload, ex=_IDEMPOTENCY_TTL_SECONDS, nx=True)


def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)
