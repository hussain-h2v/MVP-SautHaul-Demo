from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned


class VehicleType(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "vehicle_types"
    __table_args__ = (
        CheckConstraint("typical_dock_type IN ('STANDARD','REEFER','HEAVY','ANY')", name="ck_vehicle_type_dock"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    default_capacity_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    refrigerated_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    typical_dock_type: Mapped[str] = mapped_column(String(16), nullable=False)


class Vehicle(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """A truck. Dock/load compatibility (type, refrigeration, weight) is
    enforced in the scheduling service (spec section 5), never by a DB
    constraint here, because it depends on the shipment's load, not the
    vehicle in isolation."""

    __tablename__ = "vehicles"
    __table_args__ = (CheckConstraint("capacity_kg > 0", name="ck_vehicle_capacity_positive"),)

    carrier_id: Mapped[UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False, index=True)
    vehicle_type_id: Mapped[UUID] = mapped_column(ForeignKey("vehicle_types.id"), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    capacity_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    refrigeration_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    heavy_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
