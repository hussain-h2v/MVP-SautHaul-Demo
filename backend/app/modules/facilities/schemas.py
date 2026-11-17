from datetime import time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, field_validator

HHMM = Annotated[time, PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str)]


class FacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    facility_name: str
    address: str | None
    city: str
    state: str
    timezone: str
    open_time: HHMM
    close_time: HHMM
    checkin_grace_min: int
    default_unload_min: int
    active_flag: bool
    notes: str | None


class FacilityPage(BaseModel):
    total: int
    items: list[FacilityOut]


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_role: str
    contact_name: str
    email: str | None
    phone: str | None
    active_flag: bool
    missing_email: bool = False


class FacilityDetail(FacilityOut):
    contacts: list[ContactOut]
    dock_count: int


class FacilityIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    facility_name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    timezone: str = "Asia/Kolkata"
    open_time: time
    close_time: time
    checkin_grace_min: int = Field(default=30, ge=0, le=720)
    default_unload_min: int = Field(default=60, gt=0, le=1440)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError("Unknown time zone") from None
        return v

    @field_validator("close_time")
    @classmethod
    def _order(cls, v: time, info) -> time:
        o = info.data.get("open_time")
        if o and v <= o:
            raise ValueError("close_time must be after open_time")
        return v


class FacilityPatch(BaseModel):
    facility_name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = None
    state: str | None = None
    timezone: str | None = None
    open_time: time | None = None
    close_time: time | None = None
    checkin_grace_min: int | None = Field(default=None, ge=0, le=720)
    default_unload_min: int | None = Field(default=None, gt=0, le=1440)
    notes: str | None = Field(default=None, max_length=1000)
    active_flag: bool | None = None


class ContactIn(BaseModel):
    contact_role: str = Field(min_length=1, max_length=100)
    contact_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)


class ContactPatch(BaseModel):
    contact_role: str | None = None
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    active_flag: bool | None = None
