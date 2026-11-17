from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str
    payload: dict[str, Any]
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    total: int
    unread: int
    items: list[NotificationOut]
