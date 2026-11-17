"""Read-only queries for the carrier portal. They join shipments, appointments, slots, docks, check-ins, holds,
approval requests, escalations and drivers directly because those modules have no read models for this view
(recorded in docs/DECISIONS.md, decision 44). Every query starts from `base_shipments`, which carries the carrier scope."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import order_by, search
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment, FacilityCheckin
from app.modules.auth.deps import Principal
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.docks.models import Dock
from app.modules.drivers.models import Driver
from app.modules.facilities.models import Facility
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.vehicles.models import Vehicle

ACTIVE_SHIPMENT = ("ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK")
SORTS = {"code": Shipment.code, "current_status": Shipment.current_status, "priority_code": Shipment.priority_code}


def base_shipments(p: Principal, carrier_id: UUID | None) -> Select:
    """Offered shipments of one carrier (or all carriers for admin/coordinator). Carrier users can never widen it."""
    stmt = select(Shipment).where(Shipment.offer_status != "draft", Shipment.carrier_id.is_not(None))
    if p.role == "carrier_user":
        return stmt.where(Shipment.carrier_id == p.carrier_id) if p.carrier_id else stmt.where(false())
    return stmt.where(Shipment.carrier_id == carrier_id) if carrier_id else stmt


def shipment_ids(p: Principal, carrier_id: UUID | None):
    return base_shipments(p, carrier_id).with_only_columns(Shipment.id).scalar_subquery()


def _driver_scope(stmt: Select, p: Principal, carrier_id: UUID | None) -> Select:
    if p.role == "carrier_user":
        return stmt.where(Driver.carrier_id == p.carrier_id) if p.carrier_id else stmt.where(false())
    return stmt.where(Driver.carrier_id == carrier_id) if carrier_id else stmt


# ---------------------------------------------------------------- dashboard
async def dashboard_counts(db: AsyncSession, p: Principal, carrier_id: UUID | None, today_start: datetime,
                           today_end: datetime, since: datetime) -> dict:
    ships = base_shipments(p, carrier_id).subquery()
    total = (await db.execute(select(func.count()).select_from(ships))).scalar_one()
    on_road = (await db.execute(select(func.count()).select_from(ships).where(ships.c.current_status == "IN_TRANSIT"))).scalar_one()
    awaiting = (await db.execute(select(func.count()).select_from(ships).where(
        ships.c.offer_status == "accepted", ships.c.driver_id.is_(None), ships.c.current_status == "PLANNED"))).scalar_one()
    busy = select(Shipment.driver_id).where(Shipment.driver_id.is_not(None), Shipment.current_status.in_(ACTIVE_SHIPMENT))
    avail_stmt = _driver_scope(select(func.count()).select_from(Driver).where(
        Driver.driver_status == "ACTIVE", Driver.id.not_in(busy)), p, carrier_id)
    unver_stmt = _driver_scope(select(func.count()).select_from(Driver).where(
        Driver.driver_status == "ACTIVE", Driver.verified_at.is_(None)), p, carrier_id)
    upcoming = (await db.execute(
        select(func.count()).select_from(Appointment).join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(Appointment.shipment_id.in_(shipment_ids(p, carrier_id)), Appointment.is_current.is_(True),
               Appointment.appointment_status.in_(("PENDING_CONFIRMATION", "CONFIRMED")),
               AppointmentSlot.slot_start_ts >= today_start, AppointmentSlot.slot_start_ts < today_end))).scalar_one()
    secs = (await db.execute(
        select(func.coalesce(func.sum(func.extract("epoch", FacilityCheckin.unload_start_ts - FacilityCheckin.gate_in_ts)), 0))
        .where(FacilityCheckin.shipment_id.in_(shipment_ids(p, carrier_id)), FacilityCheckin.gate_in_ts >= since,
               FacilityCheckin.unload_start_ts.is_not(None), FacilityCheckin.gate_in_ts.is_not(None)))).scalar_one()
    return {"shipments_total": total, "trucks_on_road": on_road, "awaiting_assignment": awaiting,
            "drivers_available": (await db.execute(avail_stmt)).scalar_one(),
            "unverified_drivers": (await db.execute(unver_stmt)).scalar_one(),
            "upcoming_appointments_today": upcoming, "detention_hours": round(float(secs) / 3600, 1)}


async def at_risk_appointments(db: AsyncSession, p: Principal, carrier_id: UUID | None):
    """(shipment_id, slot_start) of in-transit/assigned shipments with a live appointment, for the late-truck count."""
    rows = await db.execute(
        select(Appointment.shipment_id, AppointmentSlot.slot_start_ts)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(Appointment.shipment_id.in_(shipment_ids(p, carrier_id)), Appointment.is_current.is_(True),
               Appointment.appointment_status.in_(ACTIVE_STATUSES))
        .join(Shipment, Shipment.id == Appointment.shipment_id)
        .where(Shipment.current_status.in_(("IN_TRANSIT", "ASSIGNED"))))
    return [tuple(r) for r in rows.all()]


# ---------------------------------------------------------------- tracker
async def tracker_page(db: AsyncSession, p: Principal, carrier_id: UUID | None, q, status, facility_id, driver_id,
                       limit: int, offset: int):
    stmt = base_shipments(p, carrier_id)
    if (cond := search(q, Shipment.code, Shipment.order_reference, Shipment.customer_name)) is not None:
        stmt = stmt.where(cond)
    if status:
        stmt = stmt.where(Shipment.current_status == status)
    if facility_id:
        stmt = stmt.where(Shipment.destination_facility_id == facility_id)
    if driver_id:
        stmt = stmt.where(Shipment.driver_id == driver_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(order_by(None, SORTS, Shipment.code)).limit(limit).offset(offset))).scalars().all()
    return total, rows


async def tracker_context(db: AsyncSession, ships: list[Shipment], now: datetime) -> dict:
    ids = [s.id for s in ships]
    if not ids:
        return {k: {} for k in ("vehicles", "drivers", "facilities", "appts", "checkins", "holds", "requests", "escalations")}
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle).where(Vehicle.id.in_([s.vehicle_id for s in ships if s.vehicle_id])))).scalars()}
    drivers = {d.id: d for d in (await db.execute(select(Driver).where(Driver.id.in_([s.driver_id for s in ships if s.driver_id])))).scalars()}
    facilities = {f.id: f for f in (await db.execute(select(Facility).where(Facility.id.in_({s.destination_facility_id for s in ships})))).scalars()}
    appt_rows = (await db.execute(
        select(Appointment, AppointmentSlot, Dock).join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .join(Dock, Dock.id == AppointmentSlot.dock_id)
        .where(Appointment.shipment_id.in_(ids), Appointment.is_current.is_(True), Appointment.appointment_status.in_(ACTIVE_STATUSES)))).all()
    appts = {a.shipment_id: (a, slot, dock) for a, slot, dock in appt_rows}
    checkins = {c.shipment_id: c for c in (await db.execute(select(FacilityCheckin).where(FacilityCheckin.shipment_id.in_(ids)))).scalars()}
    holds = {h.shipment_id for h in (await db.execute(select(SlotHold).where(
        SlotHold.shipment_id.in_(ids), SlotHold.status == "active", SlotHold.expires_at > now))).scalars()}
    requests: dict[UUID, str] = {}
    for r in (await db.execute(select(ApprovalRequest).where(
            ApprovalRequest.shipment_id.in_(ids), ApprovalRequest.status.in_(("waiting", "suggested", "held"))))).scalars():
        if requests.get(r.shipment_id) != "suggested":
            requests[r.shipment_id] = r.status
    escalations: dict[UUID, Escalation] = {}
    for e in (await db.execute(select(Escalation).where(Escalation.shipment_id.in_(ids)).order_by(Escalation.created_at))).scalars():
        escalations[e.shipment_id] = e
    return {"vehicles": vehicles, "drivers": drivers, "facilities": facilities, "appts": appts, "checkins": checkins,
            "holds": holds, "requests": requests, "escalations": escalations}


# ---------------------------------------------------------------- slot changes
async def slot_change_sources(db: AsyncSession, p: Principal, carrier_id: UUID | None, limit: int):
    sid = shipment_ids(p, carrier_id)
    appts = (await db.execute(select(Appointment).where(Appointment.shipment_id.in_(sid))
                              .order_by(Appointment.updated_at.desc()).limit(limit))).scalars().all()
    holds = (await db.execute(select(SlotHold).where(SlotHold.shipment_id.in_(sid), SlotHold.status == "active")
                              .order_by(SlotHold.created_at.desc()).limit(limit))).scalars().all()
    reqs = (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.shipment_id.in_(sid), ApprovalRequest.status.in_(("suggested", "rejected", "held")))
        .order_by(ApprovalRequest.updated_at.desc()).limit(limit))).scalars().all()
    escs = (await db.execute(select(Escalation).where(Escalation.shipment_id.in_(sid))
                             .order_by(Escalation.created_at.desc()).limit(limit))).scalars().all()
    return appts, holds, reqs, escs


# ---------------------------------------------------------------- reports
async def report_shipments(db: AsyncSession, p: Principal, carrier_id: UUID | None, start: datetime, end: datetime):
    stmt = (base_shipments(p, carrier_id).where(Shipment.original_eta_ts >= start, Shipment.original_eta_ts < end)
            .order_by(Shipment.original_eta_ts, Shipment.code))
    return (await db.execute(stmt)).scalars().all()


async def report_detention(db: AsyncSession, p: Principal, carrier_id: UUID | None, start: datetime, end: datetime):
    stmt = (select(Shipment, FacilityCheckin).join(FacilityCheckin, FacilityCheckin.shipment_id == Shipment.id)
            .where(Shipment.id.in_(shipment_ids(p, carrier_id)), FacilityCheckin.gate_in_ts >= start,
                   FacilityCheckin.gate_in_ts < end, FacilityCheckin.unload_start_ts.is_not(None))
            .order_by(FacilityCheckin.gate_in_ts))
    return (await db.execute(stmt)).all()


async def facility_codes(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    return {i: c for i, c in (await db.execute(select(Facility.id, Facility.code).where(Facility.id.in_(ids)))).all()}
