from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ACTOR_TYPES = ("user", "driver", "bot", "system", "ai")


class AuditLog(Base):
    """Append-only (UPDATE/DELETE blocked by trigger in migration 0003).
    Not Timestamped/Versioned on purpose: rows are immutable."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user','driver','bot','system','ai')", name="ck_audit_actor_type"),
        Index("ix_audit_entity", "entity", "entity_id"),
        Index("ix_audit_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
