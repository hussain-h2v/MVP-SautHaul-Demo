from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ScopesOut(BaseModel):
    all_facilities: bool
    facility_ids: list[UUID]
    carrier_id: UUID | None


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    locale: str
    scopes: ScopesOut
    capabilities: dict[str, str]


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class SessionOut(BaseModel):
    id: UUID
    device: str | None
    ip: str | None
    created_at: str
    current: bool
