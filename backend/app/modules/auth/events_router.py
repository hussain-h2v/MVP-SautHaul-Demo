from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.events import stream_for
from app.core.idempotency import get_redis
from app.modules.auth.deps import Principal, get_principal

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream(request: Request, p: Principal = Depends(get_principal)) -> StreamingResponse:
    redis = get_redis()
    gen = stream_for(redis, p.role, p.facility_ids, p.carrier_id, request.headers.get("last-event-id"))

    async def body():
        try:
            async for chunk in gen:
                yield chunk
        finally:
            await redis.aclose()

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
