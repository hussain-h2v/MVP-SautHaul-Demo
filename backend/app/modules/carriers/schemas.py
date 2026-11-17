from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CarrierOut(BaseModel):
    id: UUID
    code: str
    carrier_name: str
    contact_email: str | None
    contact_phone: str | None
    active_flag: bool
    allowed_vehicle_type_codes: list[str]
    driver_count: int = 0
    vehicle_count: int = 0


class CarrierDetail(CarrierOut):
    shipments_total: int = 0
    shipments_active: int = 0
    shipments_completed: int = 0
    shipments_cancelled: int = 0


class CarrierPage(BaseModel):
    total: int
    items: list[CarrierOut]


class CarrierIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    carrier_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=32)
    allowed_vehicle_type_codes: list[str] = []


class CarrierPatch(BaseModel):
    carrier_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=32)
    allowed_vehicle_type_codes: list[str] | None = None
    active_flag: bool | None = None
