from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned

ROLES = ("admin", "facility_planner", "coordinator", "carrier_user")
USER_STATUSES = ("invited", "active", "disabled")


class User(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','facility_planner','coordinator','carrier_user')", name="ck_user_role"),
        CheckConstraint("status IN ('invited','active','disabled')", name="ck_user_status"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="invited", nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserScope(Base, UUIDPK, Timestamped):
    """A planner sees specific facilities; a carrier user sees one carrier.
    Admin and coordinator are global by role and need no scope rows."""

    __tablename__ = "user_scopes"
    __table_args__ = (
        CheckConstraint(
            "(facility_id IS NOT NULL AND carrier_id IS NULL) OR (facility_id IS NULL AND carrier_id IS NOT NULL)",
            name="ck_scope_exactly_one",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    facility_id: Mapped[UUID | None] = mapped_column(ForeignKey("facilities.id"))
    carrier_id: Mapped[UUID | None] = mapped_column(ForeignKey("carriers.id"))
