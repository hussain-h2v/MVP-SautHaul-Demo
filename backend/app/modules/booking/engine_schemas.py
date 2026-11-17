from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class HoldIn(BaseModel):
    shipment_id: UUID
    slot_ids: list[UUID] = Field(min_length=1, max_length=3)
    exception_id: UUID | None = None


class HoldOut(BaseModel):
    id: UUID
    shipment_id: UUID
    shipment_code: str | None = None
    slot_ids: list[UUID]
    status: str
    expires_at: datetime
    seconds_left: int = 0


class RequestIn(BaseModel):
    shipment_id: UUID
    hold_id: UUID | None = None
    exception_id: UUID | None = None
    reason_code: str | None = Field(default=None, max_length=40)


class RequestOut(BaseModel):
    id: UUID
    shipment_id: UUID
    shipment_code: str | None = None
    status: str
    reason_code: str | None
    hold_id: UUID | None
    slot_id: UUID | None
    suggested_slot_id: UUID | None
    reason: str | None
    decision_deadline: datetime | None
    created_at: datetime


class SuggestIn(BaseModel):
    slot_ids: list[UUID] = Field(min_length=1, max_length=3)


class KeepHoldIn(BaseModel):
    extend_minutes: int = Field(default=15, ge=1, le=60)
    decision_deadline: datetime | None = None


class RejectRequestIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class BookIn(BaseModel):
    shipment_id: UUID
    slot_ids: list[UUID] = Field(min_length=1, max_length=3)


class MoveIn(BaseModel):
    slot_ids: list[UUID] = Field(min_length=1, max_length=3)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class MoveCheckOut(BaseModel):
    feasible: bool
    problems: list[str]
    needs_planner_approval: bool


class BookedOut(BaseModel):
    appointment_id: UUID
    code: str
    appointment_status: str
    is_current: bool
    slot_id: UUID
    replaced_appointment_id: UUID | None
    needs_planner_approval: bool
