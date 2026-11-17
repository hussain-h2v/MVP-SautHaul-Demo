"""Neutral outbox writer so any module can record an event in the caller's transaction."""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import OutboxEvent


def emit(db: AsyncSession, event_type: str, payload: dict) -> None:
    db.add(OutboxEvent(event_type=event_type, payload={k: (str(v) if isinstance(v, UUID) else v) for k, v in payload.items()}))
