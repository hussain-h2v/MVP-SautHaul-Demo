from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OpenRequest(BaseModel):
    id: UUID
    shipment_code: str | None
    status: str
    priority_code: str | None
    reason_code: str | None


class ActiveHold(BaseModel):
    id: UUID
    shipment_code: str | None
    expires_at: datetime


class OpenEscalation(BaseModel):
    id: UUID
    shipment_code: str | None
    reason_code: str
    status: str


class Snapshot(BaseModel):
    source: str = "rules"
    open_requests: list[OpenRequest]
    active_holds: list[ActiveHold]
    open_escalations: list[OpenEscalation]
    pending_confirmations: int
    failed_messages: int
    decisions_made_since: int


class HandoverDraft(BaseModel):
    shift_started_at: datetime
    summary: str
    snapshot: Snapshot


class HandoverIn(BaseModel):
    shift_started_at: datetime
    summary: str = Field(min_length=10, max_length=8000)
    notes: str | None = Field(default=None, max_length=4000)


class HandoverOut(BaseModel):
    id: UUID
    author_id: UUID
    author_name: str
    shift_started_at: datetime
    summary: str
    notes: str | None
    snapshot: dict
    created_at: datetime
