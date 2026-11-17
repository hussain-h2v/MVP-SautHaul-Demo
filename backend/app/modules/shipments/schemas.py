from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

DOCK_TYPES = ("ANY", "STANDARD", "REEFER", "HEAVY")
PRIORITIES = ("LOW", "NORMAL", "HIGH", "CRITICAL")


class ShipmentOut(BaseModel):
    id: UUID
    code: str
    order_reference: str
    carrier_id: UUID | None
    carrier_name: str | None = None
    driver_id: UUID | None
    driver_name: str | None = None
    vehicle_id: UUID | None
    destination_facility_id: UUID
    facility_code: str = ""
    facility_name: str = ""
    customer_name: str
    origin_name: str
    origin_city: str
    product_category: str
    load_weight_kg: int
    pallet_count: int | None
    required_dock_type: str
    temperature_control_required: bool
    priority_code: str
    requested_date: date | None
    expected_unload_min: int
    current_status: str
    offer_status: str
    offer_decline_reason: str | None
    original_eta_ts: datetime
    latest_eta_ts: datetime | None
    planned_departure_ts: datetime


class ShipmentPage(BaseModel):
    total: int
    items: list[ShipmentOut]


class _Fields(BaseModel):
    destination_facility_id: UUID
    customer_name: str = Field(min_length=1, max_length=200)
    origin_name: str = Field(min_length=1, max_length=200)
    origin_city: str = Field(min_length=1, max_length=100)
    product_category: str = Field(min_length=1, max_length=100)
    load_weight_kg: int = Field(gt=0, le=100000)
    pallet_count: int | None = Field(default=None, ge=0, le=500)
    required_dock_type: str = "ANY"
    temperature_control_required: bool = False
    priority_code: str = "NORMAL"
    expected_unload_min: int = Field(gt=0, le=1440)
    requested_date: date | None = None


def _check(d: dict[str, Any]) -> None:
    if d.get("required_dock_type", "ANY") not in DOCK_TYPES:
        raise ValueError("required_dock_type must be one of " + ", ".join(DOCK_TYPES))
    if d.get("priority_code", "NORMAL") not in PRIORITIES:
        raise ValueError("priority_code must be one of " + ", ".join(PRIORITIES))
    if d.get("temperature_control_required") and d.get("required_dock_type") in ("STANDARD", "HEAVY"):
        raise ValueError("Temperature-controlled loads need a REEFER (or ANY) dock type")


class ShipmentIn(_Fields):
    order_reference: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _v(self):
        _check(self.model_dump())
        return self


class ShipmentPatch(BaseModel):
    order_reference: str | None = Field(default=None, min_length=1, max_length=64)
    destination_facility_id: UUID | None = None
    customer_name: str | None = Field(default=None, min_length=1, max_length=200)
    origin_name: str | None = None
    origin_city: str | None = None
    product_category: str | None = None
    load_weight_kg: int | None = Field(default=None, gt=0, le=100000)
    pallet_count: int | None = Field(default=None, ge=0, le=500)
    required_dock_type: str | None = None
    temperature_control_required: bool | None = None
    priority_code: str | None = None
    expected_unload_min: int | None = Field(default=None, gt=0, le=1440)
    requested_date: date | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OfferIn(BaseModel):
    carrier_id: UUID


class TimelineEvent(BaseModel):
    ts: datetime
    kind: str
    title: str
    detail: str | None = None
    actor: str | None = None
    meta: dict[str, Any] = {}


class ThreadRef(BaseModel):
    id: UUID
    code: str
    status: str


class Timeline(BaseModel):
    events: list[TimelineEvent]
    threads: list[ThreadRef]
