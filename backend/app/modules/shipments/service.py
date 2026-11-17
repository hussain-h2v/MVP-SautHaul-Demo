from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.outbox import emit
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.listing import ImportError_, ImportResult, read_csv
from app.modules.appointments import service as appointments_service
from app.modules.audit import service as audit_service
from app.modules.auth.deps import Principal
from app.modules.eta import service as eta_service
from app.modules.shipments import repository
from app.modules.shipments.models import Shipment
from app.modules.shipments.schemas import (
    AssignmentCheck, CancelIn, Issue, OfferIn, RespondIn, ShipmentIn, ShipmentOut, ShipmentPatch, ThreadRef, Timeline,
    TimelineEvent,
)
from app.modules.slots import service as slots_service
from app.modules.whatsapp import service as whatsapp_service

IMPORT_COLUMNS = [
    "order_reference", "destination_facility_code", "customer_name", "origin_name", "origin_city",
    "product_category", "load_weight_kg", "pallet_count", "required_dock_type", "temperature_control_required",
    "priority_code", "expected_unload_min", "requested_date",
]
EDITABLE = ("PLANNED", "ASSIGNED")


async def stats_for_carrier(db: AsyncSession, carrier_id: UUID) -> dict[str, int]:
    return await repository.stats_for_carrier(db, carrier_id)


async def active_counts_by_driver(db: AsyncSession, ids: list[UUID]) -> dict[UUID, int]:
    return await repository.active_counts_by_driver(db, ids)


async def enrich(db: AsyncSession, rows: list[Shipment]) -> list[ShipmentOut]:
    from app.modules.carriers import service as carriers_service  # import cycle: carriers.service uses us
    from app.modules.drivers import service as drivers_service
    from app.modules.facilities import service as facilities_service

    carriers = await carriers_service.names(db, list({r.carrier_id for r in rows if r.carrier_id}))
    drivers = await drivers_service.names(db, list({r.driver_id for r in rows if r.driver_id}))
    facilities = await facilities_service.summaries(db, list({r.destination_facility_id for r in rows}))
    out = []
    for r in rows:
        fc, fn = facilities.get(r.destination_facility_id, ("", ""))
        out.append(ShipmentOut(
            id=r.id, code=r.code, order_reference=r.order_reference, carrier_id=r.carrier_id,
            carrier_name=carriers.get(r.carrier_id) if r.carrier_id else None, driver_id=r.driver_id,
            driver_name=drivers.get(r.driver_id) if r.driver_id else None, vehicle_id=r.vehicle_id,
            destination_facility_id=r.destination_facility_id, facility_code=fc, facility_name=fn,
            customer_name=r.customer_name, origin_name=r.origin_name, origin_city=r.origin_city,
            product_category=r.product_category, load_weight_kg=r.load_weight_kg, pallet_count=r.pallet_count,
            required_dock_type=r.required_dock_type, temperature_control_required=r.temperature_control_required,
            priority_code=r.priority_code, requested_date=r.requested_date,
            expected_unload_min=r.expected_unload_min, current_status=r.current_status, offer_status=r.offer_status,
            offer_decline_reason=r.offer_decline_reason, original_eta_ts=r.original_eta_ts,
            latest_eta_ts=r.latest_eta_ts, planned_departure_ts=r.planned_departure_ts,
        ))
    return out


async def _get(db: AsyncSession, p: Principal, shipment_id: UUID) -> Shipment:
    s = await repository.get(db, p, shipment_id)
    if s is None:
        raise NotFoundError("Shipment not found")
    return s


async def _facility(db: AsyncSession, facility_id: UUID):
    from app.modules.facilities import repository as facilities_repo

    f = await facilities_repo.summaries(db, [facility_id])
    if facility_id not in f:
        raise ValidationAppError("Destination facility not found")


def _default_eta(requested: date | None, open_time, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    day = requested or (datetime.now(zone).date() + timedelta(days=1))
    return datetime.combine(day, open_time, tzinfo=zone).astimezone(UTC)


async def _insert(db: AsyncSession, data: dict, eta: datetime) -> Shipment:
    if await repository.by_order_reference(db, data["order_reference"]):
        raise ConflictError("ORDER_EXISTS", f"Order reference {data['order_reference']} already exists")
    for _ in range(5):
        s = Shipment(code=await repository.next_code(db), carrier_id=None, driver_id=None, vehicle_id=None,
                     planned_departure_ts=eta - timedelta(hours=6), original_eta_ts=eta, current_status="PLANNED",
                     offer_status="draft", **data)
        db.add(s)
        try:
            async with db.begin_nested():
                await db.flush()
            return s
        except IntegrityError as e:
            if s in db:
                db.expunge(s)
            if "order_reference" in str(e.orig):
                raise ConflictError("ORDER_EXISTS", f"Order reference {data['order_reference']} already exists") from None
    raise ConflictError("CODE_RACE", "Could not allocate a shipment code, retry")


async def create(db: AsyncSession, body: ShipmentIn) -> Shipment:
    from app.modules.facilities import repository as facilities_repo
    from app.modules.facilities.models import Facility

    fac = await db.get(Facility, body.destination_facility_id)
    if fac is None or not fac.active_flag:
        raise ValidationAppError("Destination facility not found or inactive")
    del facilities_repo
    return await _insert(db, body.model_dump(), _default_eta(body.requested_date, fac.open_time, fac.timezone))


async def update(db: AsyncSession, p: Principal, shipment_id: UUID, body: ShipmentPatch) -> Shipment:
    s = await _get(db, p, shipment_id)
    if s.current_status not in EDITABLE:
        raise ConflictError("NOT_EDITABLE", f"A {s.current_status} shipment can no longer be edited")
    data = body.model_dump(exclude_unset=True)
    if "destination_facility_id" in data and data["destination_facility_id"] != s.destination_facility_id:
        if await appointments_service.has_active(db, s.id):
            raise ConflictError("ACTIVE_APPOINTMENT", "Cancel the appointment before changing the facility")
        await _facility(db, data["destination_facility_id"])
    merged = {"required_dock_type": s.required_dock_type, "temperature_control_required": s.temperature_control_required,
              "priority_code": s.priority_code, **data}
    from app.modules.shipments.schemas import _check

    try:
        _check(merged)
    except ValueError as e:
        raise ValidationAppError(str(e)) from None
    if "order_reference" in data and data["order_reference"] != s.order_reference:
        if await repository.by_order_reference(db, data["order_reference"]):
            raise ConflictError("ORDER_EXISTS", "Order reference already exists")
    for k, v in data.items():
        setattr(s, k, v)
    return s


async def cancel(db: AsyncSession, p: Principal, shipment_id: UUID, body: CancelIn) -> Shipment:
    s = await _get(db, p, shipment_id)
    if s.current_status in ("CANCELLED", "COMPLETED"):
        raise ConflictError("NOT_CANCELLABLE", f"Shipment is already {s.current_status}")
    if await appointments_service.has_active(db, s.id):
        raise ConflictError("ACTIVE_APPOINTMENT", "This shipment holds a dock appointment; cancel it through the booking flow first")
    s.current_status = "CANCELLED"
    s.offer_decline_reason = s.offer_decline_reason or None
    return s


async def offer(db: AsyncSession, p: Principal, shipment_id: UUID, body: OfferIn) -> Shipment:
    from app.modules.carriers import repository as carriers_repo

    s = await _get(db, p, shipment_id)
    if s.current_status != "PLANNED" or s.offer_status not in ("draft", "declined", "offered"):
        raise ConflictError("NOT_OFFERABLE", "Only unassigned planned shipments can be offered")
    carrier = await carriers_repo.get(db, p, body.carrier_id)
    if carrier is None or not carrier.active_flag:
        raise ValidationAppError("Carrier not found or inactive")
    s.carrier_id, s.offer_status, s.offer_decline_reason = carrier.id, "offered", None
    emit(db, "shipment.offered", {"shipment_id": s.id, "carrier_id": carrier.id, "code": s.code})
    return s


async def publish_offer(s: Shipment) -> None:
    try:
        await events.publish("shipment.offered", {"shipment_id": str(s.id), "code": s.code},
                             facility_id=s.destination_facility_id, carrier_id=s.carrier_id)
    except Exception:  # live updates are best-effort; the write already committed
        pass


async def import_csv(db: AsyncSession, file: UploadFile, dry_run: bool) -> ImportResult:
    from app.modules.facilities import service as facilities_service

    rows = await read_csv(file, ["order_reference", "destination_facility_code", "customer_name", "origin_name",
                                 "origin_city", "product_category", "load_weight_kg", "expected_unload_min"])
    errors: list[ImportError_] = []
    created, seen = 0, set()
    for n, row in rows:
        try:
            fac = await facilities_service.id_by_code(db, row["destination_facility_code"])
            if fac is None:
                raise ValueError(f"Unknown or inactive facility {row['destination_facility_code']}")
            requested = date.fromisoformat(row["requested_date"]) if row.get("requested_date") else None
            body = ShipmentIn(
                order_reference=row["order_reference"], destination_facility_id=fac[0],
                customer_name=row["customer_name"], origin_name=row["origin_name"], origin_city=row["origin_city"],
                product_category=row["product_category"], load_weight_kg=int(row["load_weight_kg"]),
                pallet_count=int(row["pallet_count"]) if row.get("pallet_count") else None,
                required_dock_type=(row.get("required_dock_type") or "ANY").upper(),
                temperature_control_required=row.get("temperature_control_required", "").lower() in ("1", "true", "yes", "y"),
                priority_code=(row.get("priority_code") or "NORMAL").upper(),
                expected_unload_min=int(row["expected_unload_min"]), requested_date=requested,
            )
            if body.order_reference in seen or await repository.by_order_reference(db, body.order_reference):
                raise ValueError(f"Order reference {body.order_reference} already exists")
            seen.add(body.order_reference)
            if not dry_run:
                await _insert(db, body.model_dump(), _default_eta(requested, fac[1], fac[2]))
            created += 1
        except ValidationError as e:
            errors.append(ImportError_(row=n, message="; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())))
        except (ValueError, ConflictError, ValidationAppError) as e:
            errors.append(ImportError_(row=n, message=getattr(e, "message", str(e))))
    if errors and not dry_run:
        await db.rollback()
        return ImportResult(dry_run=False, created=0, errors=errors)
    return ImportResult(dry_run=dry_run, created=created, errors=errors)


def _audit_event(a) -> TimelineEvent | None:
    after, before = a.after or {}, a.before or {}
    actor = f"{a.actor_type}:{a.actor_id}" if a.actor_id else a.actor_type
    if a.action == "insert":
        return None  # covered by the created event
    changed = sorted(after)
    if after.get("offer_status") == "offered":
        return TimelineEvent(ts=a.created_at, kind="offered", title="Offered to carrier", actor=actor,
                             meta={"carrier_id": after.get("carrier_id")})
    if after.get("offer_status") in ("accepted", "declined"):
        return TimelineEvent(ts=a.created_at, kind="offered", title=f"Carrier {after['offer_status']} the offer",
                             detail=after.get("offer_decline_reason"), actor=actor)
    if "driver_id" in after and after["driver_id"]:
        return TimelineEvent(ts=a.created_at, kind="assigned", title="Driver and vehicle assigned", actor=actor)
    if after.get("current_status") == "CANCELLED":
        return TimelineEvent(ts=a.created_at, kind="cancelled", title="Shipment cancelled", actor=actor)
    return TimelineEvent(ts=a.created_at, kind="audit", title="Updated " + ", ".join(changed), actor=actor,
                         meta={"before": {k: before.get(k) for k in changed}, "after": after})


async def timeline(db: AsyncSession, p: Principal, shipment_id: UUID) -> Timeline:
    s = await _get(db, p, shipment_id)
    ev = [TimelineEvent(ts=s.created_at, kind="created", title="Shipment created",
                        detail=f"Planned ETA {s.original_eta_ts.isoformat()}")]
    for a in await audit_service.for_entity(db, "shipments", str(s.id)):
        if (e := _audit_event(a)) is not None:
            ev.append(e)
    for u in await eta_service.history(db, s.id):
        ev.append(TimelineEvent(
            ts=u.created_at, kind="eta", title=f"ETA {u.source_type.replace('_', ' ').lower()}",
            detail=f"{u.declared_eta_ts.isoformat()} ({u.confidence_code.lower()} confidence"
                   + (f", {u.delay_reason_code.lower()}" if u.delay_reason_code else "") + ")",
            meta={"note": u.note}))
    appts = await appointments_service.for_shipment(db, s.id)
    windows = await slots_service.windows(db, [a.slot_id for a in appts])
    for a in appts:
        code, start, end = windows.get(a.slot_id, ("?", None, None))
        label = f"slot {code}" + (f" {start.isoformat()}–{end.isoformat()}" if start else "")
        note = " (replaced earlier appointment)" if a.replaced_appointment_id else ""
        ev.append(TimelineEvent(ts=a.booked_at, kind="appointment", title=f"Appointment {a.appointment_status.lower().replace('_', ' ')}",
                                detail=label + note, meta={"appointment_id": str(a.id), "is_current": a.is_current}))
        if a.cancelled_at:
            ev.append(TimelineEvent(ts=a.cancelled_at, kind="appointment", title="Appointment cancelled",
                                    detail=a.cancellation_reason or label))
    c = await appointments_service.checkin_for_shipment(db, s.id)
    if c:
        for ts, kind, title in ((c.gate_in_ts, "checkin", "Gate in"), (c.dock_in_ts, "checkin", "Docked"),
                                (c.unload_start_ts, "unload", "Unloading started"),
                                (c.unload_end_ts, "unload", "Unloading finished"), (c.gate_out_ts, "checkin", "Gate out")):
            if ts:
                ev.append(TimelineEvent(ts=ts, kind=kind, title=title, detail=c.arrival_state))
    threads = [ThreadRef(id=t.id, code=t.code, status=t.thread_status)
               for t in await whatsapp_service.threads_for_shipment(db, s.id)]
    ev.sort(key=lambda e: e.ts)
    return Timeline(events=ev, threads=threads)


async def summaries(db: AsyncSession, ids: list[UUID]) -> dict[UUID, dict]:
    """Light read model for other modules (schedule grid, affected-booking lists). No scope filter:
    callers must already have scoped the slot/appointment the shipment hangs off."""
    from sqlalchemy import select

    if not ids:
        return {}
    rows = (await db.execute(select(Shipment).where(Shipment.id.in_(ids)))).scalars().all()
    from app.modules.carriers import service as carriers_service
    from app.modules.drivers import service as drivers_service

    carriers = await carriers_service.names(db, list({r.carrier_id for r in rows if r.carrier_id}))
    drivers = await drivers_service.names(db, list({r.driver_id for r in rows if r.driver_id}))
    return {
        r.id: {"code": r.code, "carrier_name": carriers.get(r.carrier_id), "driver_name": drivers.get(r.driver_id),
               "priority_code": r.priority_code, "current_status": r.current_status, "vehicle_id": r.vehicle_id,
               "driver_id": r.driver_id, "load_weight_kg": r.load_weight_kg, "required_dock_type": r.required_dock_type,
               "expected_unload_min": r.expected_unload_min, "customer_name": r.customer_name,
               "product_category": r.product_category}
        for r in rows
    }


async def get_scoped(db: AsyncSession, p: Principal, shipment_id: UUID) -> Shipment:
    return await _get(db, p, shipment_id)


async def get_many(db: AsyncSession, ids: list[UUID]) -> dict[UUID, Shipment]:
    return await repository.get_many(db, ids)


async def inbound_for_facility(db: AsyncSession, facility_id: UUID) -> list[Shipment]:
    return await repository.inbound_for_facility(db, facility_id)


async def set_status(db: AsyncSession, shipment_id: UUID, status: str) -> None:
    s = await db.get(Shipment, shipment_id)
    if s is not None:
        s.current_status = status


async def set_latest_eta(db: AsyncSession, shipment_id: UUID, ts: datetime) -> None:
    s = await db.get(Shipment, shipment_id)
    if s is not None:
        s.latest_eta_ts = ts


async def visible_to(db: AsyncSession, p: Principal, shipment_id: UUID) -> bool:
    return await repository.get(db, p, shipment_id) is not None



async def active_counts_by_vehicle(db: AsyncSession, ids: list[UUID]) -> dict[UUID, int]:
    return await repository.active_counts_by_vehicle(db, ids)


async def history_for_driver(db: AsyncSession, driver_id: UUID) -> list[dict]:
    from app.modules.facilities import service as facilities_service

    rows = await repository.history_for_driver(db, driver_id)
    fac = await facilities_service.summaries(db, list({s.destination_facility_id for s in rows}))
    return [{"code": s.code, "current_status": s.current_status, "original_eta_ts": s.original_eta_ts,
             "facility_code": fac.get(s.destination_facility_id, ("", ""))[0]} for s in rows]


# ---------------------------------------------------------------- carrier actions: respond, assign, reassign
def _own_carrier_shipment(p: Principal, s: Shipment) -> None:
    if p.carrier_id is None or s.carrier_id != p.carrier_id:
        raise NotFoundError("Shipment not found")


async def respond(db: AsyncSession, p: Principal, shipment_id: UUID, body: RespondIn) -> Shipment:
    s = await _get(db, p, shipment_id)
    _own_carrier_shipment(p, s)
    if s.offer_status != "offered":
        raise ConflictError("NOT_OFFERED", f"This offer is already {s.offer_status}")
    if body.accept:
        s.offer_status, s.offer_decline_reason = "accepted", None
    else:
        s.offer_status, s.offer_decline_reason = "declined", body.reason.strip()
    emit(db, "shipment.offer_responded", {"shipment_id": s.id, "carrier_id": s.carrier_id, "accepted": body.accept,
                                          "reason": s.offer_decline_reason})
    return s


async def assignment_check(db: AsyncSession, p: Principal, shipment_id: UUID, driver_id: UUID,
                           vehicle_id: UUID) -> tuple[AssignmentCheck, Shipment]:
    """Blocks incompatible vehicles; warns (does not block) about a busy or unverified driver."""
    from app.modules.carriers import repository as carriers_repo
    from app.modules.drivers import service as drivers_service
    from app.modules.vehicles import service as vehicles_service

    s = await _get(db, p, shipment_id)
    _own_carrier_shipment(p, s)
    driver = await drivers_service.get_scoped(db, p, driver_id)
    vehicle, vtype = await vehicles_service.get_scoped(db, p, vehicle_id)
    problems: list[Issue] = []
    warnings: list[Issue] = []
    if driver.driver_status != "ACTIVE":
        problems.append(Issue(code="DRIVER_INACTIVE", message=f"{driver.driver_name} is {driver.driver_status.lower()}"))
    if not vehicle.active_flag:
        problems.append(Issue(code="VEHICLE_INACTIVE", message=f"{vehicle.registration_number} is retired"))
    if (s.temperature_control_required or s.required_dock_type == "REEFER") and not vehicle.refrigeration_capable:
        problems.append(Issue(code="VEHICLE_NOT_REFRIGERATED", message="This load is temperature controlled; the vehicle has no refrigeration"))
    if s.required_dock_type == "HEAVY" and not vehicle.heavy_capable:
        problems.append(Issue(code="VEHICLE_NOT_HEAVY", message="This load needs the heavy dock; the vehicle is not heavy-capable"))
    if s.load_weight_kg > vehicle.capacity_kg:
        problems.append(Issue(code="LOAD_EXCEEDS_CAPACITY", message=f"Load is {s.load_weight_kg} kg; the vehicle carries {vehicle.capacity_kg} kg"))
    carrier = await carriers_repo.get(db, p, s.carrier_id)
    allowed = list(carrier.allowed_vehicle_type_codes or []) if carrier else []
    if allowed and vtype.code not in allowed:
        problems.append(Issue(code="VEHICLE_TYPE_NOT_ALLOWED", message=f"Vehicle type {vtype.code} is not allowed for your carrier"))
    busy = await repository.active_counts_by_driver(db, [driver.id])
    on_other = busy.get(driver.id, 0) - (1 if s.driver_id == driver.id else 0)
    if on_other > 0:
        warnings.append(Issue(code="DRIVER_ON_ANOTHER_SHIPMENT", message=f"{driver.driver_name} is already on {on_other} active shipment(s)"))
    vbusy = await repository.active_counts_by_vehicle(db, [vehicle.id])
    if vbusy.get(vehicle.id, 0) - (1 if s.vehicle_id == vehicle.id else 0) > 0:
        warnings.append(Issue(code="VEHICLE_ON_ANOTHER_SHIPMENT", message=f"{vehicle.registration_number} is already on an active shipment"))
    if driver.verified_at is None:
        warnings.append(Issue(code="DRIVER_NOT_VERIFIED", message="No verified WhatsApp number: the driver cannot get slot messages"))
    elif not driver.whatsapp_opt_in:
        warnings.append(Issue(code="DRIVER_OPTED_OUT", message="The driver opted out of WhatsApp messages"))
    return AssignmentCheck(problems=problems, warnings=warnings, driver_language=driver.preferred_language,
                           driver_verified=driver.verified_at is not None), s


async def assign(db: AsyncSession, p: Principal, shipment_id: UUID, driver_id: UUID, vehicle_id: UUID):
    check, s = await assignment_check(db, p, shipment_id, driver_id, vehicle_id)
    if s.offer_status != "accepted":
        raise ConflictError("NOT_ACCEPTED", "Accept the offer before assigning a driver")
    if s.current_status not in ("PLANNED", "ASSIGNED"):
        raise ConflictError("NOT_ASSIGNABLE", f"A {s.current_status} shipment cannot be (re)assigned here")
    if s.driver_id is not None:
        raise ConflictError("ALREADY_ASSIGNED", "A driver is already assigned; use reassign with a reason")
    if check.problems:
        raise ValidationAppError("This driver or vehicle cannot take the load", {"problems": [i.model_dump() for i in check.problems]})
    s.driver_id, s.vehicle_id, s.current_status = driver_id, vehicle_id, "ASSIGNED"
    emit(db, "shipment.assigned", {"shipment_id": s.id, "driver_id": driver_id, "vehicle_id": vehicle_id, "carrier_id": s.carrier_id})
    return s, check


async def reassign(db: AsyncSession, p: Principal, shipment_id: UUID, driver_id: UUID, vehicle_id: UUID, reason: str):
    check, s = await assignment_check(db, p, shipment_id, driver_id, vehicle_id)
    if s.driver_id is None:
        raise ConflictError("NOT_ASSIGNED", "Nothing to reassign yet; assign a driver first")
    if s.current_status in ("COMPLETED", "CANCELLED", "IN_DOCK"):
        raise ConflictError("NOT_ASSIGNABLE", f"A {s.current_status} shipment cannot be reassigned")
    if check.problems:
        raise ValidationAppError("This driver or vehicle cannot take the load", {"problems": [i.model_dump() for i in check.problems]})
    old_driver, old_vehicle = s.driver_id, s.vehicle_id
    s.driver_id, s.vehicle_id = driver_id, vehicle_id
    emit(db, "shipment.reassigned", {"shipment_id": s.id, "carrier_id": s.carrier_id, "reason": reason,
                                     "old_driver_id": old_driver, "new_driver_id": driver_id,
                                     "old_vehicle_id": old_vehicle, "new_vehicle_id": vehicle_id})
    return s, check
