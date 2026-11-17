from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned


class HandoverRecord(Base, UUIDPK, Timestamped, Versioned):
    """End-of-shift handover: a summary the coordinator reviewed and edited, plus a snapshot of what was open."""

    __tablename__ = "handover_records"

    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    shift_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(String(8000), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(4000))
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
