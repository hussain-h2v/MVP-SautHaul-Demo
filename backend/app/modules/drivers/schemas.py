from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    carrier_id: UUID
    driver_name: str
    driver_status: str
    preferred_language: str
    whatsapp_opt_in: bool


class DriverPage(BaseModel):
    total: int
    items: list[DriverOut]
