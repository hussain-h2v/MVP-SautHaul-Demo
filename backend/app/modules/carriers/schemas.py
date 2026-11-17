from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CarrierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    carrier_name: str
    contact_email: str | None
    active_flag: bool


class CarrierPage(BaseModel):
    total: int
    items: list[CarrierOut]
