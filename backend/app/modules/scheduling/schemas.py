from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OptionsIn(BaseModel):
    shipment_id: UUID
    effective_eta: datetime | None = None
    latest_finish: datetime | None = None
    limit: int = Field(default=5, ge=1, le=20)
    escalate_if_none: bool = False


class OptionOut(BaseModel):
    rank: int
    slot_ids: list[UUID]
    slot_codes: list[str]
    dock_code: str
    dock_type: str
    start: datetime
    end: datetime
    needs_planner_approval: bool
    reasons: list[str]
    explanation: str


class EtaOut(BaseModel):
    ts: datetime
    source: str
    confidence: str
    upper_ts: datetime | None
    requires_human_review: bool


class OptionsOut(BaseModel):
    shipment_id: UUID
    eta: EtaOut | None
    total_feasible: int
    options: list[OptionOut]
    rejections: dict[str, int]
    escalation_id: UUID | None = None
    note: str | None = None
