from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DriverOut(BaseModel):
    id: UUID
    code: str
    carrier_id: UUID
    carrier_name: str = ""
    driver_name: str
    phone: str
    whatsapp_number: str | None
    preferred_language: str
    whatsapp_opt_in: bool
    verified: bool
    driver_status: str
    licence_number: str
    active_shipments: int = 0
    last_activity: datetime | None = None


class DriverPage(BaseModel):
    total: int
    items: list[DriverOut]


LANGUAGES = ("en", "hi", "te", "mr", "gu", "pa", "ta", "kn", "bn")
_E164 = r"^\+[1-9]\d{7,14}$"


class DriverIn(BaseModel):
    driver_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(pattern=_E164)
    whatsapp_number: str | None = Field(default=None, pattern=_E164)
    preferred_language: str = "en"
    licence_number: str = Field(min_length=4, max_length=64)
    home_base_city: str | None = Field(default=None, max_length=100)

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError("Unsupported language; choose one of " + ", ".join(LANGUAGES))
        return v


class DriverPatch(BaseModel):
    driver_name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=_E164)
    whatsapp_number: str | None = Field(default=None, pattern=_E164)
    preferred_language: str | None = None
    licence_number: str | None = Field(default=None, min_length=4, max_length=64)
    home_base_city: str | None = Field(default=None, max_length=100)
    driver_status: str | None = None

    @field_validator("preferred_language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is not None and v not in LANGUAGES:
            raise ValueError("Unsupported language")
        return v

    @field_validator("driver_status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("ACTIVE", "OFF_DUTY", "INACTIVE"):
            raise ValueError("driver_status must be ACTIVE, OFF_DUTY or INACTIVE")
        return v


class HistoryRow(BaseModel):
    code: str
    current_status: str
    facility_code: str
    original_eta_ts: datetime


class DriverDetail(DriverOut):
    home_base_city: str | None
    history: list[HistoryRow]


class VerificationSent(BaseModel):
    sent: bool
    expires_at: datetime
    dev_code: str | None = None


class VerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class VerifyOut(BaseModel):
    verified: bool
