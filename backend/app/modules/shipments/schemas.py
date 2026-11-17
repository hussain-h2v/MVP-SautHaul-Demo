from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    carrier_id: UUID
    driver_id: UUID
    destination_facility_id: UUID
    priority_code: str
    required_dock_type: str
    current_status: str
    expected_unload_min: int


class ShipmentPage(BaseModel):
    total: int
    items: list[ShipmentOut]
