from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.permissions import ROLES
from app.modules.auth import service as auth_service
from app.modules.auth.deps import Principal, require
from app.modules.users.models import User, UserScope

router = APIRouter(prefix="/users", tags=["users"])


class UserAdminOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    status: str
    locale: str
    facility_ids: list[UUID]
    carrier_id: UUID | None


class InviteIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: str
    facility_ids: list[UUID] = []
    carrier_id: UUID | None = None


class InviteOut(UserAdminOut):
    invite_token: str


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    status: str | None = None
    facility_ids: list[UUID] | None = None
    carrier_id: UUID | None = None


def _validate(role: str, facility_ids: list[UUID], carrier_id: UUID | None) -> None:
    if role not in ROLES:
        raise ValidationAppError("Unknown role")
    if role == "facility_planner" and not facility_ids:
        raise ValidationAppError("A facility planner needs at least one facility")
    if role == "carrier_user" and carrier_id is None:
        raise ValidationAppError("A carrier user needs a carrier")


async def _out(db: AsyncSession, u: User) -> UserAdminOut:
    scopes = (await db.execute(select(UserScope).where(UserScope.user_id == u.id))).scalars().all()
    return UserAdminOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role, status=u.status, locale=u.locale,
        facility_ids=[s.facility_id for s in scopes if s.facility_id],
        carrier_id=next((s.carrier_id for s in scopes if s.carrier_id), None),
    )


@router.get("", response_model=list[UserAdminOut])
async def list_users(_: Principal = Depends(require("manage_master", "R")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User).order_by(User.email))).scalars().all()
    return [await _out(db, u) for u in rows]


@router.post("", response_model=InviteOut, status_code=201)
async def invite_user(body: InviteIn, _: Principal = Depends(require("manage_master", "W")),
                      db: AsyncSession = Depends(get_db)):
    _validate(body.role, body.facility_ids, body.carrier_id)
    email = body.email.lower()
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise ConflictError("EMAIL_EXISTS", "A user with this email already exists")
    user = User(email=email, full_name=body.full_name, role=body.role, status="invited")
    db.add(user)
    await db.flush()
    for fid in body.facility_ids if body.role == "facility_planner" else []:
        db.add(UserScope(user_id=user.id, facility_id=fid))
    if body.role == "carrier_user":
        db.add(UserScope(user_id=user.id, carrier_id=body.carrier_id))
    token = await auth_service.create_invite(db, user)
    await db.commit()
    return InviteOut(**(await _out(db, user)).model_dump(), invite_token=token)


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(user_id: UUID, body: UserPatch, _: Principal = Depends(require("manage_master", "W")),
                      db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError("User not found")
    current = await _out(db, user)
    role = body.role or user.role
    fac = body.facility_ids if body.facility_ids is not None else current.facility_ids
    car = body.carrier_id if body.carrier_id is not None else current.carrier_id
    _validate(role, fac, car)
    if body.full_name:
        user.full_name = body.full_name
    if body.status:
        if body.status not in ("active", "disabled", "invited"):
            raise ValidationAppError("Unknown status")
        user.status = body.status
        if body.status == "disabled":
            await auth_service.revoke_all(db, user.id)
    user.role = role
    if body.role or body.facility_ids is not None or body.carrier_id is not None:
        await db.execute(delete(UserScope).where(UserScope.user_id == user.id))
        for fid in fac if role == "facility_planner" else []:
            db.add(UserScope(user_id=user.id, facility_id=fid))
        if role == "carrier_user":
            db.add(UserScope(user_id=user.id, carrier_id=car))
    await db.commit()
    return await _out(db, user)


@router.post("/{user_id}/force-logout", status_code=204)
async def force_logout(user_id: UUID, _: Principal = Depends(require("manage_master", "W")),
                       db: AsyncSession = Depends(get_db)) -> None:
    await auth_service.revoke_all(db, user_id)
    await db.commit()
