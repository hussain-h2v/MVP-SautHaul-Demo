from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

REQUIRED_DOCK_TYPES = ("ANY", "STANDARD", "REEFER", "HEAVY")
PRIORITY_CODES = ("LOW", "NORMAL", "HIGH", "CRITICAL")
SHIPMENT_STATUSES = (
    "PLANNED", "ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK", "COMPLETED", "CANCELLED",
)


class Shipment(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """original_eta_ts/latest_eta_ts are carried for backward-compatible
    display only; the authoritative effective ETA is computed by the eta
    module from eta_updates history (ETA precedence, spec section 5)."""

    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("load_weight_kg > 0", name="ck_shipment_weight_positive"),
        CheckConstraint("pallet_count IS NULL OR pallet_count >= 0", name="ck_shipment_pallets_nonneg"),
        CheckConstraint("expected_unload_min > 0", name="ck_shipment_unload_positive"),
        CheckConstraint("required_dock_type IN ('ANY','STANDARD','REEFER','HEAVY')", name="ck_shipment_dock_type"),
        CheckConstraint("priority_code IN ('LOW','NORMAL','HIGH','CRITICAL')", name="ck_shipment_priority"),
        CheckConstraint(
            "current_status IN ('PLANNED','ASSIGNED','IN_TRANSIT','AT_GATE','WAITING','IN_DOCK','COMPLETED','CANCELLED')",
            name="ck_shipment_status",
        ),
    )

    order_reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    carrier_id: Mapped[UUID] = mapped_column(ForeignKey("carriers.id"), nullable=False, index=True)
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"), nullable=False, index=True)
    vehicle_id: Mapped[UUID] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    origin_name: Mapped[str] = mapped_column(String(200), nullable=False)
    origin_city: Mapped[str] = mapped_column(String(100), nullable=False)
    destination_facility_id: Mapped[UUID] = mapped_column(
        ForeignKey("facilities.id"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_category: Mapped[str] = mapped_column(String(100), nullable=False)
    load_weight_kg: Mapped[int] = mapped_column(Integer, nullable=False)
    pallet_count: Mapped[int | None] = mapped_column(Integer)
    required_dock_type: Mapped[str] = mapped_column(String(16), default="ANY", nullable=False)
    temperature_control_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority_code: Mapped[str] = mapped_column(String(16), default="NORMAL", nullable=False)
    planned_departure_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_departure_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_eta_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_eta_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_unload_min: Mapped[int] = mapped_column(Integer, nullable=False)
    current_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
