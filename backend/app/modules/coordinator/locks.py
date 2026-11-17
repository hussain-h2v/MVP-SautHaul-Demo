"""Soft locks so two coordinators never work the same item at once. Redis keys with a TTL: a crashed browser frees
the item automatically. The owner is shown by name; only the owner may decide while the lock is live."""
import json
from uuid import UUID

from redis.asyncio import Redis

from app.core.errors import ConflictError

LOCK_TTL_SECONDS = 600
KINDS = ("request", "exception", "hold", "escalation", "failed_message", "eta_change")


def _key(kind: str, item_id: UUID | str) -> str:
    return f"lock:{kind}:{item_id}"


class ClaimedError(ConflictError):
    def __init__(self, owner: dict) -> None:
        super().__init__("CLAIMED", f"Being handled by {owner['name']}", {"claimed_by": owner})


async def owner_of(redis: Redis, kind: str, item_id: UUID | str) -> dict | None:
    raw = await redis.get(_key(kind, item_id))
    return json.loads(raw) if raw else None


async def owners(redis: Redis, items: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    if not items:
        return {}
    vals = await redis.mget([_key(k, i) for k, i in items])
    return {it: json.loads(v) for it, v in zip(items, vals, strict=True) if v}


async def claim(redis: Redis, kind: str, item_id: UUID | str, user_id: UUID, name: str) -> dict:
    me = {"id": str(user_id), "name": name}
    if await redis.set(_key(kind, item_id), json.dumps(me), nx=True, ex=LOCK_TTL_SECONDS):
        return me
    current = await owner_of(redis, kind, item_id)
    if current is None:  # expired between the two calls
        return await claim(redis, kind, item_id, user_id, name)
    if current["id"] != str(user_id):
        raise ClaimedError(current)
    await redis.expire(_key(kind, item_id), LOCK_TTL_SECONDS)  # owner renewing
    return me


async def release(redis: Redis, kind: str, item_id: UUID | str, user_id: UUID) -> None:
    current = await owner_of(redis, kind, item_id)
    if current and current["id"] == str(user_id):
        await redis.delete(_key(kind, item_id))


async def require_free(redis: Redis, kind: str, item_id: UUID | str, user_id: UUID) -> None:
    """Decisions are blocked while someone else holds the lock; an unlocked item may be worked directly."""
    current = await owner_of(redis, kind, item_id)
    if current and current["id"] != str(user_id):
        raise ClaimedError(current)
