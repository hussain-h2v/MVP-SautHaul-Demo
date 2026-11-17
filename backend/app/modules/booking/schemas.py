from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PendingOut(BaseModel):
    appointment_id: UUID
    code: str
    shipment_id: UUID
    shipment_code: str
    carrier_name: str | None
    driver_name: str | None
    priority_code: str
    slot_id: UUID
    slot_code: str
    dock_code: str
    slot_start_ts: datetime
    slot_end_ts: datetime
    booked_at: datetime
    expires_at: datetime
    reason: str


class AppointmentOut(BaseModel):
    appointment_id: UUID
    code: str
    appointment_status: str
    is_current: bool


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class YardRow(BaseModel):
    shipment_id: UUID
    shipment_code: str
    carrier_name: str | None
    driver_name: str | None
    priority_code: str
    load: str
    appointment_id: UUID | None
    appointment_status: str | None
    slot_code: str | None
    planned_dock_code: str | None
    actual_dock_code: str | None
    slot_start_ts: datetime | None
    slot_end_ts: datetime | None
    eta_ts: datetime | None
    gate_in_ts: datetime | None
    queue_state: str | None
    queue_position: int | None
    waiting_min: int
    arrival_state: str | None
    unload_start_ts: datetime | None
    unload_end_ts: datetime | None
    overrun_min: int | None
    dock_mismatch: bool
    checkin_id: UUID | None


class FinishOut(YardRow):
    unload_min: int
    detention_min: int


class YardOut(BaseModel):
    queue: list[YardRow]
    in_dock: list[YardRow]
    expected: list[YardRow]
    done: list[YardRow]


class CheckInIn(BaseModel):
    shipment_id: UUID


class AssignDockIn(BaseModel):
    dock_id: UUID


class NoShowIn(BaseModel):
    appointment_id: UUID


class InboundRow(BaseModel):
    shipment_id: UUID
    shipment_code: str
    carrier_name: str | None
    driver_name: str | None
    priority_code: str
    required_dock_type: str
    current_status: str
    eta_ts: datetime | None
    eta_source: str | None
    eta_confidence: str | None
    appointment_id: UUID | None
    appointment_status: str | None
    slot_code: str | None
    dock_code: str | None
    slot_start_ts: datetime | None
    late: bool
    at_risk: bool
