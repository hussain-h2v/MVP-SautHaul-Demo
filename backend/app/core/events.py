"""Real-time fan-out: events go into a Redis Stream so every API instance can serve SSE
and clients can resume with Last-Event-ID. Each event carries its scope; the stream
endpoint filters per principal, so a carrier never sees another carrier's events."""
import json
from collections.abc import AsyncIterator
from uuid import UUID

from redis.asyncio import Redis

from app.core.idempotency import get_redis

STREAM = "events:stream"


async def publish(type_: str, payload: dict, *, facility_id: UUID | None = None,
                  carrier_id: UUID | None = None, redis: Redis | None = None) -> None:
    own = redis is None
    r = redis or get_redis()
    try:
        await r.xadd(
            STREAM,
            {"type": type_, "data": json.dumps(payload, default=str),
             "facility_id": str(facility_id or ""), "carrier_id": str(carrier_id or "")},
            maxlen=10000, approximate=True,
        )
    finally:
        if own:
            await r.aclose()


def visible(role: str, facility_ids: set[UUID], carrier_id: UUID | None, facility: str, carrier: str) -> bool:
    if role in ("admin", "coordinator"):
        return True
    if role == "facility_planner":
        return bool(facility) and UUID(facility) in facility_ids
    if role == "carrier_user":
        return bool(carrier) and carrier_id is not None and UUID(carrier) == carrier_id
    return False


async def stream_for(redis: Redis, role: str, facility_ids: set[UUID], carrier_id: UUID | None,
                     last_id: str | None, block_ms: int = 15000) -> AsyncIterator[str]:
    cursor = last_id or "$"
    yield "retry: 3000\n\n"
    while True:
        res = await redis.xread({STREAM: cursor}, block=block_ms, count=50)
        if not res:
            yield ": keepalive\n\n"
            continue
        for _, entries in res:
            for entry_id, f in entries:
                cursor = entry_id
                if visible(role, facility_ids, carrier_id, f.get("facility_id", ""), f.get("carrier_id", "")):
                    yield f"id: {entry_id}\nevent: {f['type']}\ndata: {f['data']}\n\n"



async def publish_inbox_changed(reason: str, **extra) -> None:
    try:
        await publish("inbox.changed", {"reason": reason, **extra})
    except Exception:  # best effort: the write already committed
        pass
