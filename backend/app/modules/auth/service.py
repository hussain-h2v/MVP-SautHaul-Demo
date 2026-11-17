from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ForbiddenError
from app.core.permissions import capabilities_for
from app.core.security import create_access_token, hash_password, new_token, sha256, verify_password
from app.modules.auth.deps import Principal, UnauthorizedError
from app.modules.auth.models import Session, UserToken
from app.modules.auth.schemas import ScopesOut, UserOut
from app.modules.users.models import User

MAX_FAILURES = 5
LOCK_MINUTES = 15
LOGIN_LIMIT_PER_MIN = 20


class LockedError(AppError):
    status_code = 423

    def __init__(self) -> None:
        super().__init__("ACCOUNT_LOCKED", "Account temporarily locked after repeated failures")


class RateLimitedError(AppError):
    status_code = 429

    def __init__(self) -> None:
        super().__init__("RATE_LIMITED", "Too many attempts, slow down")


async def rate_limit(redis: Redis | None, key: str, limit: int, window_s: int = 60) -> None:
    if redis is None:
        return
    try:
        n = await redis.incr(f"rl:{key}")
        if n == 1:
            await redis.expire(f"rl:{key}", window_s)
        if n > limit:
            raise RateLimitedError()
    except RateLimitedError:
        raise
    except Exception:  # Redis outage must not take auth down
        return


def user_out(p: Principal) -> UserOut:
    return UserOut(
        id=p.user_id, email=p.email, full_name=p.full_name, role=p.role, locale=p.locale,
        scopes=ScopesOut(all_facilities=p.all_facilities, facility_ids=sorted(p.facility_ids), carrier_id=p.carrier_id),
        capabilities=capabilities_for(p.role),
    )


async def _issue_session(db: AsyncSession, user: User, device: str | None, ip: str | None) -> tuple[str, str]:
    refresh = new_token()
    sess = Session(
        user_id=user.id, refresh_hash=sha256(refresh), device=(device or "")[:300], ip=ip,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().jwt_refresh_ttl_days),
    )
    db.add(sess)
    await db.flush()
    return create_access_token(user.id, user.role, sess.id), refresh


async def login(db: AsyncSession, email: str, password: str, device: str | None, ip: str | None) -> tuple[User, str, str]:
    user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is not None and user.locked_until and user.locked_until > now:
        raise LockedError()
    if user is None or user.status != "active" or not user.password_hash or not verify_password(password, user.password_hash):
        if user is not None and user.status == "active":
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILURES:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
            await db.commit()
        raise UnauthorizedError("Invalid email or password")
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    access, refresh = await _issue_session(db, user, device, ip)
    await db.commit()
    return user, access, refresh


async def refresh(db: AsyncSession, refresh_token: str) -> tuple[User, str, str]:
    sess = (await db.execute(select(Session).where(Session.refresh_hash == sha256(refresh_token)))).scalar_one_or_none()
    now = datetime.now(UTC)
    if sess is None or sess.revoked_at or sess.expires_at < now:
        raise UnauthorizedError("Session expired")
    user = await db.get(User, sess.user_id)
    if user is None or user.status != "active":
        raise UnauthorizedError()
    from app.core.security import create_access_token as mk

    new_refresh = new_token()
    sess.refresh_hash = sha256(new_refresh)
    await db.commit()
    return user, mk(user.id, user.role, sess.id), new_refresh


async def logout(db: AsyncSession, refresh_token: str | None) -> None:
    if refresh_token:
        await db.execute(
            update(Session).where(Session.refresh_hash == sha256(refresh_token), Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()


async def revoke_all(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
    )


async def create_invite(db: AsyncSession, user: User, hours: int = 72) -> str:
    token = new_token()
    db.add(UserToken(user_id=user.id, token_hash=sha256(token), purpose="invite",
                     expires_at=datetime.now(UTC) + timedelta(hours=hours)))
    return token


async def accept_invite(db: AsyncSession, token: str, password: str) -> None:
    row = (await db.execute(select(UserToken).where(UserToken.token_hash == sha256(token)))).scalar_one_or_none()
    if row is None or row.used_at or row.expires_at < datetime.now(UTC):
        raise ForbiddenError("Invite link is invalid or expired")
    user = await db.get(User, row.user_id)
    user.password_hash = hash_password(password)
    user.status = "active"
    row.used_at = datetime.now(UTC)
    await db.commit()


async def change_password(db: AsyncSession, user_id: UUID, current: str, new: str) -> None:
    user = await db.get(User, user_id)
    if not user or not user.password_hash or not verify_password(current, user.password_hash):
        raise ForbiddenError("Current password is incorrect")
    user.password_hash = hash_password(new)
    await revoke_all(db, user_id)
    await db.commit()
