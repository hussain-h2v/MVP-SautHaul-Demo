from uuid import UUID

from pydantic import BaseModel, Field


class VehicleOut(BaseModel):
    id: UUID
    code: str
    carrier_id: UUID
    carrier_name: str = ""
    vehicle_type_code: str
    vehicle_type_description: str
    registration_number: str
    capacity_kg: int
    refrigeration_capable: bool
    heavy_capable: bool
    active_flag: bool
    assigned_shipments: int = 0


class VehiclePage(BaseModel):
    total: int
    items: list[VehicleOut]


class VehicleIn(BaseModel):
    vehicle_type_code: str
    registration_number: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9 -]+$")
    capacity_kg: int = Field(gt=0, le=100000)
    refrigeration_capable: bool = False
    heavy_capable: bool = False


class VehiclePatch(BaseModel):
    vehicle_type_code: str | None = None
    registration_number: str | None = Field(default=None, min_length=4, max_length=32, pattern=r"^[A-Za-z0-9 -]+$")
    capacity_kg: int | None = Field(default=None, gt=0, le=100000)
    refrigeration_capable: bool | None = None
    heavy_capable: bool | None = None
    active_flag: bool | None = None
