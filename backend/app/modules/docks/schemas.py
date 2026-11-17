from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOCK_TYPES = ("STANDARD", "REEFER", "HEAVY")
DOCK_STATUSES = ("ACTIVE", "MAINTENANCE", "OUT_OF_SERVICE", "INACTIVE")
EVENT_TYPES = ("MAINTENANCE", "BREAKDOWN", "CAPACITY_REDUCTION", "REOPENED", "MANUAL_BLOCK")


class DockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    facility_id: UUID
    dock_code: str
    dock_type: str
    supports_refrigerated: bool
    max_vehicle_weight_kg: int
    dock_status: str
    compatible_vehicle_type_codes: list[str]
    notes: str | None


class DockIn(BaseModel):
    facility_id: UUID
    dock_code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    dock_type: str = "STANDARD"
    supports_refrigerated: bool = False
    max_vehicle_weight_kg: int = Field(gt=0, le=200000)
    compatible_vehicle_type_codes: list[str] = []
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _v(self):
        if self.dock_type not in DOCK_TYPES:
            raise ValueError("dock_type must be one of " + ", ".join(DOCK_TYPES))
        if self.dock_type == "REEFER":
            self.supports_refrigerated = True
        return self


class DockPatch(BaseModel):
    dock_type: str | None = None
    supports_refrigerated: bool | None = None
    max_vehicle_weight_kg: int | None = Field(default=None, gt=0, le=200000)
    dock_status: str | None = None
    compatible_vehicle_type_codes: list[str] | None = None
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _v(self):
        if self.dock_type is not None and self.dock_type not in DOCK_TYPES:
            raise ValueError("dock_type must be one of " + ", ".join(DOCK_TYPES))
        if self.dock_status is not None and self.dock_status not in DOCK_STATUSES:
            raise ValueError("dock_status must be one of " + ", ".join(DOCK_STATUSES))
        return self


class AffectedAppointment(BaseModel):
    appointment_id: UUID
    appointment_code: str
    shipment_code: str | None
    slot_code: str
    slot_start_ts: datetime
    appointment_status: str


class DockEventOut(BaseModel):
    id: UUID
    dock_id: UUID
    dock_code: str
    event_type: str
    event_start_ts: datetime
    event_end_ts: datetime | None
    reason: str
    resolved: bool
    affected_count: int = 0


class DockEventIn(BaseModel):
    dock_id: UUID
    event_type: str
    event_start_ts: datetime
    event_end_ts: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _v(self):
        if self.event_type not in EVENT_TYPES:
            raise ValueError("event_type must be one of " + ", ".join(EVENT_TYPES))
        if self.event_end_ts is not None and self.event_end_ts <= self.event_start_ts:
            raise ValueError("event_end_ts must be after event_start_ts")
        return self


class DockEventPreviewIn(BaseModel):
    dock_id: UUID
    event_start_ts: datetime
    event_end_ts: datetime | None = None


class AffectedList(BaseModel):
    affected_appointments: list[AffectedAppointment]


class DockEventCreated(DockEventOut):
    affected_appointments: list[AffectedAppointment]
