from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserRef(BaseModel):
    id: UUID
    name: str


class ThreadItem(BaseModel):
    id: UUID
    code: str
    driver_id: UUID
    driver_name: str
    driver_language: str
    driver_phone: str
    shipment_code: str | None
    thread_status: str
    thread_intent: str
    last_message_text: str | None
    last_message_ts: datetime | None
    requires_review: bool
    taken_over_by: UserRef | None
    bot_paused: bool


class ThreadPage(BaseModel):
    total: int
    items: list[ThreadItem]


class MessageOut(BaseModel):
    id: UUID
    sender_type: str
    text: str
    translation: str | None = None
    ts: datetime
    is_duplicate: bool
    parsed_intent: str | None
    extracted_eta_ts: datetime | None
    requires_human_review: bool


class ThreadMessages(BaseModel):
    thread: ThreadItem
    messages: list[MessageOut]


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ReplyOut(BaseModel):
    message: MessageOut
    deliverable: bool


class DraftOut(BaseModel):
    text: str
    language: str
    source: str = "rules"
