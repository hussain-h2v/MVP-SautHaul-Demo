from datetime import date, time
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned


class Facility(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    __tablename__ = "facilities"
    __table_args__ = (
        CheckConstraint("checkin_grace_min >= 0", name="ck_facility_grace_nonneg"),
        CheckConstraint("default_unload_min > 0", name="ck_facility_unload_positive"),
    )

    facility_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    checkin_grace_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    default_unload_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))


class FacilityContact(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "facility_contacts"

    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    contact_role: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FacilityRule(Base, UUIDPK, Timestamped, Versioned):
    """rule_type/rule_value stay free-text (as in the reference schema) since
    the rule catalogue (last allowed start, operating hours, approval
    thresholds) is interpreted by the scheduling service, not the DB."""

    __tablename__ = "facility_rules"

    facility_id: Mapped[UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
