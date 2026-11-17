from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class BoardRow(BaseModel):
    shipment_id: UUID
    code: str
    carrier_name: str | None
    driver_name: str | None
    facility_code: str
    priority_code: str
    current_status: str
    eta_ts: datetime | None
    eta_confidence: str | None
    slot_code: str | None
    dock_code: str | None
    slot_start_ts: datetime | None
    late_min: int | None


class Stages(BaseModel):
    travelling: list[BoardRow] = []
    late: list[BoardRow] = []
    in_yard: list[BoardRow] = []
    unloading: list[BoardRow] = []
    done: list[BoardRow] = []


class BoardOut(BaseModel):
    date: date | None
    stages: Stages
    counts: dict[str, int]
