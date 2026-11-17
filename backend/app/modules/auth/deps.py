from dataclasses import dataclass, field
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Actor, current_actor
from app.core.db import get_db
from app.core.errors import AppError, ForbiddenError
from app.core.permissions import allowed
from app.core.security import decode_token
from app.modules.users.models import User, UserScope

SAFE = {"GET", "HEAD", "OPTIONS"}


class UnauthorizedError(AppError):
    status_code = 401

    def __init__(self, message: str = "Not authenticated"):
        super().__init__("UNAUTHENTICATED", message)


@dataclass
class Principal:
    user_id: UUID
    email: str
    full_name: str
    role: str
    locale: str
    facility_ids: set[UUID] = field(default_factory=set)
    carrier_id: UUID | None = None

    @property
    def all_facilities(self) -> bool:
        return self.role in ("admin", "coordinator")

    def can(self, capability: str, level: str = "R") -> bool:
        return allowed(self.role, capability, level)


def check_csrf(request: Request) -> None:
    if request.method in SAFE:
        return
    cookie, header = request.cookies.get("csrf_token"), request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise ForbiddenError("CSRF token missing or invalid")


async def load_principal(db: AsyncSession, user_id: UUID) -> Principal | None:
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    scopes = (await db.execute(select(UserScope).where(UserScope.user_id == user.id))).scalars().all()
    return Principal(
        user_id=user.id, email=user.email, full_name=user.full_name, role=user.role, locale=user.locale,
        facility_ids={s.facility_id for s in scopes if s.facility_id},
        carrier_id=next((s.carrier_id for s in scopes if s.carrier_id), None),
    )


async def get_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal:
    token = request.cookies.get("access_token")
    if not token:
        raise UnauthorizedError()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid or expired token") from None
    if payload.get("type") != "access":
        raise UnauthorizedError()
    check_csrf(request)
    from app.modules.auth.models import Session

    sess = await db.get(Session, UUID(payload["sid"]))
    if sess is None or sess.revoked_at is not None:
        raise UnauthorizedError("Session revoked")
    principal = await load_principal(db, UUID(payload["sub"]))
    if principal is None:
        raise UnauthorizedError()
    current_actor.set(Actor("user", str(principal.user_id), request.client.host if request.client else None))
    return principal


def require(capability: str, level: str = "R"):
    async def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(capability, level):
            raise ForbiddenError(f"Requires {capability}:{level}")
        return principal

    return dep


def require_any(*grants: tuple[str, str]):
    """Allow if the principal holds at least one of the (capability, level) grants."""

    async def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not any(principal.can(c, lv) for c, lv in grants):
            raise ForbiddenError("Not permitted")
        return principal

    return dep
