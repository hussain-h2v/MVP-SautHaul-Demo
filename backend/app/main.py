import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import audit_events
from app.core.config import get_settings
from app.core.context import Actor, current_actor, current_trace_id
from app.core.errors import AppError, app_error_handler
from app.core.logging import configure_logging, get_logger
from app.modules.analytics.router import router as analytics_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.events_router import router as events_router
from app.modules.auth.router import router as auth_router
from app.modules.booking.router import router as booking_router
from app.modules.carriers.router import router as carriers_router
from app.modules.drivers.router import router as drivers_router
from app.modules.facilities.router import router as facilities_router
from app.modules.settings.router import router as settings_router
from app.modules.shipments.router import router as shipments_router
from app.modules.users.router import router as users_router
from app.modules.vehicles.router import router as vehicles_router

settings = get_settings()
configure_logging(settings.debug)
audit_events.install()
log = get_logger("http")

app = FastAPI(title="SetuHaul Dock Scheduling API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)


@app.middleware("http")
async def trace_and_headers(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    current_trace_id.set(trace_id)
    current_actor.set(Actor("system", None, request.client.host if request.client else None))
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled", path=request.url.path, trace_id=trace_id)
        response = JSONResponse({"error": {"code": "INTERNAL", "message": "Internal error"}}, status_code=500)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    log.info("request", method=request.method, path=request.url.path, status=response.status_code,
             ms=round((time.perf_counter() - start) * 1000, 1), trace_id=trace_id)
    return response


@app.middleware("http")
async def idempotency(request: Request, call_next):
    key = request.headers.get("idempotency-key")
    if request.method not in ("POST", "PUT", "PATCH", "DELETE") or not key or not request.url.path.startswith("/api/"):
        return await call_next(request)
    import hashlib
    import json

    from fastapi import Response

    from app.core.idempotency import cache_response, get_cached_response, get_redis

    who = request.cookies.get("access_token", "")
    cache_key = hashlib.sha256(f"{who}|{request.method}|{request.url.path}|{key}".encode()).hexdigest()
    redis = get_redis()
    try:
        hit = await get_cached_response(redis, cache_key)
        if hit:
            return Response(hit["body"], status_code=hit["status_code"], media_type="application/json",
                            headers={"Idempotent-Replay": "true"})
        response = await call_next(request)
        if 200 <= response.status_code < 300 and response.headers.get("content-type", "").startswith("application/json"):
            body = b"".join([c async for c in response.body_iterator])
            await cache_response(redis, cache_key, response.status_code, body.decode())
            return Response(body, status_code=response.status_code, headers=dict(response.headers),
                            media_type="application/json")
        return response
    finally:
        await redis.aclose()


api = APIRouter(prefix="/api/v1")
for r in (auth_router, users_router, settings_router, audit_router, events_router, facilities_router,
          carriers_router, drivers_router, shipments_router, vehicles_router,
          booking_router, analytics_router):
    api.include_router(r)
from app.modules.docks.router import router as docks_router  # noqa: E402
from app.modules.slots.router import router as slots_router  # noqa: E402

api.include_router(docks_router)
api.include_router(slots_router)
app.include_router(api)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    from sqlalchemy import text

    from app.core.db import engine
    from app.core.idempotency import get_redis

    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    redis = get_redis()
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    finally:
        await redis.aclose()
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)
