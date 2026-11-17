from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.idempotency import get_redis
from app.core.security import new_token
from app.modules.auth import service
from app.modules.auth.deps import Principal, check_csrf, get_principal, load_principal
from app.modules.auth.models import Session
from app.modules.auth.schemas import AcceptInviteIn, ChangePasswordIn, LoginIn, SessionOut, UserOut
from app.core.security import decode_token

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
SECURE = settings.env == "production"


def _set_cookies(resp: Response, access: str, refresh: str) -> None:
    resp.set_cookie("access_token", access, httponly=True, secure=SECURE, samesite="lax",
                    max_age=settings.jwt_access_ttl_minutes * 60, path="/")
    resp.set_cookie("refresh_token", refresh, httponly=True, secure=SECURE, samesite="lax",
                    max_age=settings.jwt_refresh_ttl_days * 86400, path="/api/v1/auth")
    resp.set_cookie("csrf_token", new_token()[:32], httponly=False, secure=SECURE, samesite="lax",
                    max_age=settings.jwt_refresh_ttl_days * 86400, path="/")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> UserOut:
    redis = get_redis()
    try:
        await service.rate_limit(redis, f"login:{_client_ip(request)}", service.LOGIN_LIMIT_PER_MIN)
    finally:
        await redis.aclose()
    current_actor.set(Actor("user", None, _client_ip(request)))
    user, access, refresh = await service.login(
        db, body.email, body.password, request.headers.get("user-agent"), _client_ip(request)
    )
    _set_cookies(response, access, refresh)
    principal = await load_principal(db, user.id)
    return service.user_out(principal)  # type: ignore[arg-type]


@router.post("/refresh", status_code=204)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    check_csrf(request)
    token = request.cookies.get("refresh_token")
    if not token:
        from app.modules.auth.deps import UnauthorizedError

        raise UnauthorizedError()
    _, access, new_refresh = await service.refresh(db, token)
    _set_cookies(response, access, new_refresh)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    check_csrf(request)
    await service.logout(db, request.cookies.get("refresh_token"))
    for name, path in (("access_token", "/"), ("refresh_token", "/api/v1/auth"), ("csrf_token", "/")):
        response.delete_cookie(name, path=path)


@router.get("/me", response_model=UserOut)
async def me(principal: Principal = Depends(get_principal)) -> UserOut:
    return service.user_out(principal)


@router.post("/accept-invite", status_code=204)
async def accept_invite(body: AcceptInviteIn, db: AsyncSession = Depends(get_db)) -> None:
    await service.accept_invite(db, body.token, body.password)


@router.post("/change-password", status_code=204)
async def change_password(body: ChangePasswordIn, principal: Principal = Depends(get_principal),
                          db: AsyncSession = Depends(get_db)) -> None:
    await service.change_password(db, principal.user_id, body.current_password, body.new_password)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(request: Request, principal: Principal = Depends(get_principal),
                   db: AsyncSession = Depends(get_db)) -> list[SessionOut]:
    sid = decode_token(request.cookies["access_token"]).get("sid")
    rows = (await db.execute(
        select(Session).where(Session.user_id == principal.user_id, Session.revoked_at.is_(None))
        .order_by(Session.created_at.desc())
    )).scalars().all()
    return [SessionOut(id=s.id, device=s.device, ip=s.ip, created_at=s.created_at.isoformat(), current=str(s.id) == sid)
            for s in rows]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: UUID, principal: Principal = Depends(get_principal),
                         db: AsyncSession = Depends(get_db)) -> None:
    from datetime import UTC, datetime

    res = await db.execute(
        update(Session).where(Session.id == session_id, Session.user_id == principal.user_id)
        .values(revoked_at=datetime.now(UTC))
    )
    if res.rowcount == 0:
        raise NotFoundError("Session not found")
    await db.commit()
