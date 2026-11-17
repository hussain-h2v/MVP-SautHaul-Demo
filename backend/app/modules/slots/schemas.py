from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, model_validator

from app.modules.docks.schemas import AffectedAppointment

HHMM = Annotated[time, PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str)]


class SlotOut(BaseModel):
    id: UUID
    code: str
    dock_id: UUID
    dock_code: str
    start: datetime
    end: datetime
    slot_status: str
    block_reason: str | None
    booked: bool


class Template(BaseModel):
    dock_type: str
    start: time
    end: time
    length_min: int = Field(ge=15, le=480)

    @model_validator(mode="after")
    def _v(self):
        if self.dock_type not in ("STANDARD", "REEFER", "HEAVY"):
            raise ValueError("dock_type must be STANDARD, REEFER or HEAVY")
        if self.end <= self.start:
            raise ValueError("template end must be after start")
        return self


class GenerateIn(BaseModel):
    facility_id: UUID
    date_from: date
    date_to: date
    templates: list[Template] = Field(min_length=1, max_length=3)
    dry_run: bool = True

    @model_validator(mode="after")
    def _v(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        if (self.date_to - self.date_from).days > 30:
            raise ValueError("Generate at most 31 days at a time")
        return self


class PerDock(BaseModel):
    dock_code: str
    count: int


class GenerateOut(BaseModel):
    dry_run: bool
    to_create: int
    skipped_overlap: int
    per_dock: list[PerDock]


class BulkStatusIn(BaseModel):
    slot_ids: list[UUID] = Field(min_length=1, max_length=1000)
    status: str
    reason: str | None = Field(default=None, max_length=500)
    dry_run: bool = False
    force: bool = False

    @model_validator(mode="after")
    def _v(self):
        if self.status not in ("OPEN", "BLOCKED", "CLOSED"):
            raise ValueError("status must be OPEN, BLOCKED or CLOSED")
        if self.status != "OPEN" and not (self.reason and len(self.reason.strip()) >= 3):
            raise ValueError("A reason is required when blocking or closing slots")
        return self


class BulkStatusOut(BaseModel):
    applied: bool
    updated: int
    affected_appointments: list[AffectedAppointment]


class CopyDayIn(BaseModel):
    facility_id: UUID
    from_date: date
    to_dates: list[date] = Field(min_length=1, max_length=31)
    dry_run: bool = True


class CopyDayOut(BaseModel):
    dry_run: bool
    to_create: int
    skipped_overlap: int


class FacilityRef(BaseModel):
    id: UUID
    code: str
    facility_name: str
    timezone: str
    open_time: HHMM
    close_time: HHMM


class GridEvent(BaseModel):
    event_type: str
    reason: str


class GridAppointment(BaseModel):
    id: UUID
    code: str
    status: str
    shipment_code: str | None
    carrier_name: str | None
    driver_name: str | None
    priority_code: str | None


class GridSlot(BaseModel):
    slot_id: UUID
    code: str
    start: datetime
    end: datetime
    state: str
    block_reason: str | None
    history_state: str | None
    event: GridEvent | None
    appointment: GridAppointment | None


class GridDock(BaseModel):
    id: UUID
    code: str
    dock_code: str
    dock_type: str
    dock_status: str
    slots: list[GridSlot]


class ScheduleOut(BaseModel):
    facility: FacilityRef
    date: date
    docks: list[GridDock]


class SlotDetail(BaseModel):
    slot: SlotOut
    appointment: dict | None
    shipment: dict | None
    driver: dict | None
    vehicle: dict | None
    eta: dict | None
    history: list[dict]
