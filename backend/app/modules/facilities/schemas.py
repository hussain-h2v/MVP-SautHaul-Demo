from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    facility_name: str
    city: str
    state: str
    timezone: str
    active_flag: bool


class FacilityPage(BaseModel):
    total: int
    items: list[FacilityOut]
