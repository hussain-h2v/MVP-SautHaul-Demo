from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK


class Session(Base, UUIDPK, Timestamped):
    """Refresh-token session. Only the SHA-256 of the rotating token is stored."""

    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    device: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserToken(Base, UUIDPK, Timestamped):
    """One-time invite / password-reset links (hash only)."""

    __tablename__ = "user_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('invite','reset')", name="ck_token_purpose"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
