from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class UserRef(BaseModel):
    id: UUID
    name: str


class InboxItem(BaseModel):
    key: str
    kind: str
    id: UUID
    shipment_id: UUID | None
    shipment_code: str | None
    carrier_name: str | None
    facility_code: str | None
    priority_code: str
    status: str
    title: str
    summary: str
    created_at: datetime
    expires_at: datetime | None = None
    claimed_by: dict | None = None


class Counters(BaseModel):
    requests: int = 0
    exceptions: int = 0
    holds_expiring: int = 0
    escalations: int = 0
    failed_messages: int = 0
    eta_changes: int = 0
    total: int = 0


class InboxOut(BaseModel):
    counters: Counters
    items: list[InboxItem]


class ClaimIn(BaseModel):
    kind: str
    id: UUID


class ClaimOut(BaseModel):
    claimed_by: dict
    expires_at: datetime


class EscalateIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class EscalationOut(BaseModel):
    id: UUID
    shipment_id: UUID | None
    shipment_code: str | None = None
    carrier_name: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None
    reason_code: str
    status: str
    handoff_record: dict[str, Any]
    assigned_to: dict | None = None
    resolution: str | None = None
    created_at: datetime
    closed_at: datetime | None = None


class AssignIn(BaseModel):
    user_id: UUID | None = None


class StatusIn(BaseModel):
    status: str


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=5, max_length=1000)


class DecideIn(BaseModel):
    winner_request_id: UUID
    group_request_ids: list[UUID] = Field(min_length=2, max_length=20)
    override_reason: str | None = Field(default=None, max_length=500)


class DecideOut(BaseModel):
    approved_appointment_id: UUID
    overrode_policy: bool
    policy_winner_request_id: UUID


class ExtendIn(BaseModel):
    minutes: int = Field(ge=1, le=60)
