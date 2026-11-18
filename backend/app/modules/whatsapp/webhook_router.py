"""Public WhatsApp Cloud API webhook (mounted without the /api/v1 prefix at /webhooks/whatsapp).
GET answers Meta's subscription challenge. POST verifies X-Hub-Signature-256, stores the raw payload and returns 200
immediately; the worker does the processing."""
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.idempotency import get_redis
from app.modules.auth.service import RateLimitedError, rate_limit
from app.modules.whatsapp import processor

router = APIRouter(tags=["whatsapp-webhook"])
PER_IP_PER_MINUTE = 600


@router.get("/webhooks/whatsapp")
async def verify(request: Request):
    q = request.query_params
    token = get_settings().whatsapp_verify_token
    if token and q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    return JSONResponse({"error": {"code": "FORBIDDEN", "message": "Verification failed"}}, status_code=403)


async def _enqueue(event_id) -> None:
    """Best effort: the 5-second cron job picks up anything that is not enqueued."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await asyncio.wait_for(create_pool(RedisSettings.from_dsn(get_settings().redis_url)), 1.0)
        try:
            await pool.enqueue_job("process_whatsapp_event", str(event_id))
        finally:
            await pool.aclose()
    except Exception:  # noqa: BLE001
        pass


@router.post("/webhooks/whatsapp")
async def receive(request: Request, db: AsyncSession = Depends(get_db)):
    redis = get_redis()
    try:
        await rate_limit(redis, f"wa-webhook:{request.client.host if request.client else 'unknown'}", PER_IP_PER_MINUTE)
    except RateLimitedError:
        return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests"}}, status_code=429)
    finally:
        await redis.aclose()
    body = await request.body()
    try:
        ev = await processor.ingest(db, body, request.headers.get("x-hub-signature-256"))
    except processor.WebhookError as e:
        return JSONResponse({"error": {"code": "WEBHOOK_REJECTED", "message": e.message}}, status_code=e.status)
    await db.commit()
    await _enqueue(ev.id)
    return {"status": "received"}
