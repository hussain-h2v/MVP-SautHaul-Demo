from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DashboardOut(BaseModel):
    drivers_available: int
    trucks_on_road: int
    late_trucks: int
    awaiting_assignment: int
    upcoming_appointments_today: int
    detention_hours: float
    unverified_drivers: int
    shipments_total: int


class LoadOut(BaseModel):
    required_dock_type: str
    temperature_control_required: bool
    weight_kg: int


class VehicleRef(BaseModel):
    id: UUID
    registration_number: str


class DriverRef(BaseModel):
    id: UUID
    name: str
    language: str


class FacilityRef(BaseModel):
    id: UUID
    code: str
    name: str


class AppointmentRef(BaseModel):
    id: UUID
    status: str
    slot_code: str
    dock_code: str
    start: datetime
    end: datetime


class EtaRef(BaseModel):
    ts: datetime | None
    source: str | None
    confidence: str | None
    declared_by: str


class CheckinRef(BaseModel):
    arrival_state: str | None
    gate_in_ts: datetime | None
    queue_state: str | None


class EscalationRef(BaseModel):
    status: str
    reason_code: str


class TrackerRow(BaseModel):
    shipment_id: UUID
    code: str
    order_reference: str
    current_status: str
    load: LoadOut
    vehicle: VehicleRef | None
    driver: DriverRef | None
    facility: FacilityRef
    appointment: AppointmentRef | None
    eta: EtaRef
    checkin: CheckinRef | None
    hold_state: str
    escalation: EscalationRef | None


class TrackerPage(BaseModel):
    total: int
    items: list[TrackerRow]


class SlotChange(BaseModel):
    ts: datetime
    shipment_id: UUID
    shipment_code: str
    kind: str
    reason: str | None
    slot_code: str | None
    start: datetime | None


class CarrierReport(BaseModel):
    kind: str
    columns: list[str]
    rows: list[dict[str, Any]]
