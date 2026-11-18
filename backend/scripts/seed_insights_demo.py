"""Demo history so the insights, reports and dashboards have something to show: about 60 days of past appointments, gate
check-ins, delays, requests, escalations, offers and dock events for the seeded facilities and carriers.
Deterministic (fixed random seed), idempotent, and tagged so it can be removed again:
  shipments  order_reference 'DMI-...' (code 'SHPH...')      slots  code 'HIS-...'
  threads 'THH...'  exceptions 'EXH...'  appointments 'APH...'  dock events reason 'demo-history: ...'
Usage: python -m scripts.seed_insights_demo [--clear] [--force]     (--force = clear then recreate)"""
import asyncio
import random
import sys
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.core.db import async_session_factory
from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.booking.models import ApprovalRequest, Escalation, SlotClaim, SlotHold
from app.modules.carriers.models import Carrier
from app.modules.docks.models import Dock, DockStatusEvent
from app.modules.drivers.models import Driver
from app.modules.eta.models import EtaUpdate
from app.modules.exceptions.models import DriverException
from app.modules.facilities.models import Facility
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.users.models import User
from app.modules.vehicles.models import Vehicle
from app.modules.whatsapp.models import ChatThread

IST = ZoneInfo("Asia/Kolkata")
DAYS = 60
TAG = "DMI-"
CARRIER_LATE = {"CAR001": 0.12, "CAR002": 0.30, "CAR003": 0.21, "CAR004": 0.16}
LANES = {"CAR001": ["Delhi", "Kanpur", "Chandigarh"], "CAR002": ["Ahmedabad", "Jodhpur", "Mumbai"], "CAR003": ["Mumbai", "Jodhpur", "Delhi"], "CAR004": ["Chandigarh", "Ahmedabad", "Kanpur"]}
LANE_BIAS = {"Ahmedabad": 1.35, "Jodhpur": 1.25, "Mumbai": 1.15, "Kanpur": 1.0, "Delhi": 0.8, "Chandigarh": 0.9}
CAUSES = [("TRAFFIC", 45), ("BREAKDOWN", 15), ("WEATHER", 10), ("LOADING_DELAY", 10), ("LATE_DEPARTURE", 10), ("ROUTE_ISSUE", 5), ("OTHER", 5)]
ESC_REASONS = [("NO_FEASIBLE_SLOT", 30), ("NO_ACCEPTABLE_OPTION", 25), ("DRIVER_DECLINED_OFFER", 15), ("LOW_CONFIDENCE", 15), ("DISPUTE", 8), ("SAFETY", 3), ("TURN_LIMIT", 4)]
PRIORITIES = [("LOW", 15), ("NORMAL", 55), ("HIGH", 24), ("CRITICAL", 6)]
CUSTOMERS = ["RajRetail Distribution", "NorthWest Retail", "StyleMart Rajasthan", "CareSupply Rajasthan", "IndustrialHub", "FreshKart Foods", "Metro Cash Carry"]
PRODUCTS = ["Packaged FMCG", "Auto components", "Apparel", "Electronics", "Pharma", "Dairy (chilled)"]


def pick(rnd: random.Random, pairs: list[tuple[str, int]]) -> str:
    return rnd.choices([p[0] for p in pairs], [p[1] for p in pairs])[0]


async def clear(db) -> None:
    ids = "(SELECT id FROM shipments WHERE order_reference LIKE 'DMI-%')"
    for sql in (
        f"DELETE FROM escalations WHERE shipment_id IN {ids}", f"DELETE FROM approval_requests WHERE shipment_id IN {ids}",
        f"DELETE FROM slot_holds WHERE shipment_id IN {ids}", f"DELETE FROM driver_exceptions WHERE shipment_id IN {ids}",
        "DELETE FROM chat_messages WHERE thread_id IN (SELECT id FROM chat_threads WHERE code LIKE 'THH%')",
        "DELETE FROM chat_threads WHERE code LIKE 'THH%'", f"DELETE FROM eta_updates WHERE shipment_id IN {ids}",
        f"DELETE FROM facility_checkins WHERE shipment_id IN {ids}", f"DELETE FROM slot_claims WHERE appointment_id IN (SELECT id FROM appointments WHERE shipment_id IN {ids})",
        f"DELETE FROM appointments WHERE shipment_id IN {ids}",
        "DELETE FROM shipments WHERE order_reference LIKE 'DMI-%'", "DELETE FROM dock_status_events WHERE reason LIKE 'demo-history:%'",
        "DELETE FROM appointment_slots WHERE code LIKE 'HIS-%'",
    ):
        await db.execute(text(sql))
    await db.commit()
    print("demo insights history removed")


async def main(do_clear: bool, force: bool) -> None:
    async with async_session_factory() as db:
        if do_clear or force:
            await clear(db)
            if do_clear:
                return
        if (await db.execute(text("SELECT count(*) FROM shipments WHERE order_reference LIKE 'DMI-%'"))).scalar_one():
            print("demo insights history already present (use --force to rebuild)")
            return
        rnd = random.Random(11)
        facilities = (await db.execute(select(Facility).order_by(Facility.code))).scalars().all()
        carriers = {c.code: c for c in (await db.execute(select(Carrier))).scalars().all()}
        drivers: dict = {}
        for d in (await db.execute(select(Driver))).scalars().all():
            drivers.setdefault(d.carrier_id, []).append(d)
        vehicles: dict = {}
        for v in (await db.execute(select(Vehicle))).scalars().all():
            vehicles.setdefault(v.carrier_id, []).append(v)
        coord = (await db.execute(select(User).where(User.role == "coordinator"))).scalars().first()
        if not facilities or not carriers or coord is None:
            raise SystemExit("Run scripts.seed_reference and scripts.seed_demo_users first")
        driver_bias = {d.id: rnd.uniform(0.6, 1.5) for ds in drivers.values() for d in ds}
        today = datetime.now(IST).date()
        counters = {"ship": 0, "appt": 0, "thr": 0, "exc": 0}
        carrier_list = [c for c in carriers.values() if drivers.get(c.id) and vehicles.get(c.id)]
        made = {"slots": 0, "appointments": 0, "checkins": 0, "delays": 0, "requests": 0, "escalations": 0}

        for fac in facilities:
            docks = (await db.execute(select(Dock).where(Dock.facility_id == fac.id, Dock.dock_status == "ACTIVE").order_by(Dock.dock_code))).scalars().all()
            short = fac.code.split("-")[1]
            for back in range(DAYS, 0, -1):
                day: date = today - timedelta(days=back)
                weekend = day.weekday() >= 5
                for dock in docks:
                    hours = range(fac.open_time.hour, fac.close_time.hour)
                    for h in hours:
                        start = datetime.combine(day, time(h), tzinfo=IST).astimezone(UTC)
                        scode = f"HIS-{short}-{dock.dock_code}-{day:%y%m%d}{h:02d}00"
                        slot = AppointmentSlot(id=uuid4(), code=scode, facility_id=fac.id, dock_id=dock.id, slot_start_ts=start, slot_end_ts=start + timedelta(hours=1), slot_status="OPEN",
                                               created_at=start - timedelta(days=3), updated_at=start - timedelta(days=3))
                        db.add(slot)
                        made["slots"] += 1
                        base = 0.78 if not weekend else 0.34
                        base *= {"STANDARD": 1.0, "REEFER": 0.62, "HEAVY": 0.4}.get(dock.dock_type, 1.0)
                        if 9 <= h <= 12 or 15 <= h <= 17:
                            base += 0.12
                        if rnd.random() > min(base, 0.97):
                            continue
                        await _booking(db, rnd, counters, made, fac, dock, slot, start, carrier_list, drivers, vehicles, driver_bias, coord)
                await db.flush()
                if back % 5 == 0:
                    await db.commit()
            # a few dock events per facility
            for _ in range(4):
                dock = rnd.choice(docks)
                when = datetime.combine(today - timedelta(days=rnd.randint(2, DAYS - 1)), time(rnd.randint(8, 13)), tzinfo=IST).astimezone(UTC)
                kind = rnd.choice(["MAINTENANCE", "BREAKDOWN", "CAPACITY_REDUCTION"])
                db.add(DockStatusEvent(dock_id=dock.id, event_type=kind, event_start_ts=when, event_end_ts=when + timedelta(hours=rnd.randint(2, 6)),
                                       reason=f"demo-history: {kind.lower().replace('_', ' ')}", created_at=when, updated_at=when))
        for fac in facilities:  # tomorrow-ish days: confirmed bookings in a deliberately awkward order, so the optimiser has something to propose
            await _future(db, rnd, counters, fac, today, carrier_list, drivers, vehicles)
        # offers: some declined shipments (no appointment)
        for _ in range(26):
            c = rnd.choice(carrier_list)
            fac = rnd.choice(facilities)
            counters["ship"] += 1
            when = datetime.now(UTC) - timedelta(days=rnd.randint(1, DAYS - 1), hours=rnd.randint(0, 20))
            declined = rnd.random() < 0.3
            db.add(Shipment(code=f"SHPH{counters['ship']:05d}", order_reference=f"{TAG}{counters['ship']:05d}", carrier_id=c.id, origin_name="Demo origin", origin_city=rnd.choice(LANES[c.code]),
                            destination_facility_id=fac.id, customer_name=rnd.choice(CUSTOMERS), product_category=rnd.choice(PRODUCTS), load_weight_kg=9000,
                            planned_departure_ts=when, original_eta_ts=when + timedelta(hours=8), expected_unload_min=50, current_status="CANCELLED" if declined else "PLANNED",
                            offer_status="declined" if declined else "accepted", offer_decline_reason="Capacity not available" if declined else None,
                            created_at=when, updated_at=when))
        await db.commit()
        print("demo insights history created:", made, "shipments:", counters["ship"])


async def _future(db, rnd, counters, fac, today, carrier_list, drivers, vehicles) -> None:
    docks = (await db.execute(select(Dock).where(Dock.facility_id == fac.id, Dock.dock_status == "ACTIVE", Dock.dock_type == "STANDARD").order_by(Dock.dock_code).limit(2))).scalars().all()
    short = fac.code.split("-")[1]
    for ahead in (3, 4):
        day = today + timedelta(days=ahead)
        slots = {}
        for dock in docks:
            for h in range(fac.open_time.hour, fac.close_time.hour):
                start = datetime.combine(day, time(h), tzinfo=IST).astimezone(UTC)
                slot = AppointmentSlot(id=uuid4(), code=f"HIS-{short}-{dock.dock_code}-{day:%y%m%d}{h:02d}00", facility_id=fac.id, dock_id=dock.id, slot_start_ts=start,
                                       slot_end_ts=start + timedelta(hours=1), slot_status="OPEN")
                db.add(slot)
                slots[(dock.id, h)] = (slot, start)
        await db.flush()
        for i in range(8):
            dock = docks[i % len(docks)]
            h = 9 + i // len(docks) * 1 if i < 4 else 12 + (i - 4) // len(docks)
            slot, start = slots[(dock.id, h)]
            early_high = i >= 4
            priority = rnd.choice(["HIGH", "CRITICAL"]) if early_high else rnd.choice(["LOW", "NORMAL"])
            eta = datetime.combine(day, time(8, 30), tzinfo=IST).astimezone(UTC) if early_high else start
            car = rnd.choice(carrier_list)
            drv, veh = rnd.choice(drivers[car.id]), rnd.choice(vehicles[car.id])
            counters["ship"] += 1
            n = counters["ship"]
            booked = datetime.now(UTC) - timedelta(hours=(40 - i * 3 if not early_high else 6 - (i - 4)))
            sh = Shipment(id=uuid4(), code=f"SHPH{n:05d}", order_reference=f"{TAG}{n:05d}", carrier_id=car.id, driver_id=drv.id, vehicle_id=veh.id, origin_name="Delhi depot", origin_city="Delhi",
                          destination_facility_id=fac.id, customer_name=rnd.choice(CUSTOMERS), product_category="Packaged FMCG", load_weight_kg=9000, pallet_count=12,
                          required_dock_type="ANY", priority_code=priority, planned_departure_ts=eta - timedelta(hours=6), original_eta_ts=eta, expected_unload_min=50,
                          current_status="ASSIGNED", requested_date=day, offer_status="accepted", created_at=booked, updated_at=booked)
            db.add(sh)
            await db.flush()
            counters["appt"] += 1
            appt = Appointment(code=f"APH{counters['appt']:06d}", shipment_id=sh.id, slot_id=slot.id, appointment_status="CONFIRMED", booking_source="PLANNER", is_current=True,
                               booked_at=booked, confirmed_at=booked, created_at=booked, updated_at=booked)
            db.add(appt)
            await db.flush()
            db.add(SlotClaim(slot_id=slot.id, appointment_id=appt.id, active=True))
    await db.flush()


async def _booking(db, rnd, counters, made, fac, dock, slot, start, carrier_list, drivers, vehicles, driver_bias, coord) -> None:
    car = rnd.choices(carrier_list, [3, 3, 2, 2][: len(carrier_list)])[0]
    drv = rnd.choice(drivers[car.id])
    veh = rnd.choice(vehicles[car.id])
    origin = rnd.choice(LANES[car.code])
    counters["ship"] += 1
    n = counters["ship"]
    reefer, heavy = dock.dock_type == "REEFER", dock.dock_type == "HEAVY"
    priority = pick(rnd, PRIORITIES)
    unload = rnd.randint(40, 58) if not (reefer or heavy) else rnd.randint(50, 75)
    booked = start - timedelta(days=rnd.randint(1, 4), hours=rnd.randint(0, 10))
    sh = Shipment(id=uuid4(), code=f"SHPH{n:05d}", order_reference=f"{TAG}{n:05d}", carrier_id=car.id, driver_id=drv.id, vehicle_id=veh.id, origin_name=f"{origin} depot", origin_city=origin,
                  destination_facility_id=fac.id, customer_name=rnd.choice(CUSTOMERS), product_category="Dairy (chilled)" if reefer else rnd.choice(PRODUCTS),
                  load_weight_kg=min(dock.max_vehicle_weight_kg - 500, rnd.randint(7000, 19000) if not heavy else rnd.randint(24000, 33000)), pallet_count=rnd.randint(8, 24),
                  required_dock_type="REEFER" if reefer else ("HEAVY" if heavy else "ANY"), temperature_control_required=reefer, priority_code=priority,
                  planned_departure_ts=start - timedelta(hours=rnd.randint(6, 14)), original_eta_ts=start, expected_unload_min=unload, current_status="COMPLETED",
                  requested_date=start.astimezone(IST).date(), offer_status="accepted", created_at=booked - timedelta(days=1), updated_at=start)
    db.add(sh)
    counters["appt"] += 1
    status_roll = rnd.random()
    status = "NO_SHOW" if status_roll < 0.06 else ("CANCELLED" if status_roll < 0.09 else "COMPLETED")
    if status == "CANCELLED":
        sh.current_status = "CANCELLED"
    elif status == "NO_SHOW":
        sh.current_status = "PLANNED"
    appt = Appointment(code=f"APH{counters['appt']:06d}", shipment_id=sh.id, slot_id=slot.id, appointment_status=status, booking_source=rnd.choice(["PLANNER", "PLANNER", "DRIVER_CHAT", "SCHEDULING_TOOL"]),
                       is_current=status != "CANCELLED", booked_at=booked, confirmed_at=booked + timedelta(minutes=rnd.randint(2, 90)),
                       cancelled_at=start - timedelta(hours=rnd.randint(2, 20)) if status == "CANCELLED" else None,
                       cancellation_reason="Carrier cancelled" if status == "CANCELLED" else None, created_at=booked, updated_at=start)
    await db.flush()
    db.add(appt)
    made["appointments"] += 1
    if rnd.random() < 0.08:  # replaced an earlier booking: a slot move
        counters["appt"] += 1
        old = Appointment(code=f"APH{counters['appt']:06d}", shipment_id=sh.id, slot_id=slot.id, appointment_status="CANCELLED", booking_source="PLANNER", is_current=False,
                          booked_at=booked - timedelta(hours=3), cancelled_at=booked, cancellation_reason="Moved to a new slot", created_at=booked - timedelta(hours=3), updated_at=booked)
        db.add(old)
        await db.flush()
        appt.replaced_appointment_id = old.id
    if status != "COMPLETED":
        return
    late_p = CARRIER_LATE[car.code] * driver_bias[drv.id] * LANE_BIAS[origin]
    late = rnd.random() < min(late_p, 0.7)
    offset = rnd.randint(25, 130) if late else int(rnd.gauss(-8, 10))
    gate_in = start + timedelta(minutes=offset)
    if late and rnd.random() < 0.65:
        await _delay_flow(db, rnd, counters, made, sh, drv, start, offset, car, fac, coord)
    dock_in = max(gate_in, start) + timedelta(minutes=rnd.randint(1, 12 if not late else 35))
    unload_start = dock_in + timedelta(minutes=rnd.randint(0, 8))
    unload_end = unload_start + timedelta(minutes=max(25, unload + rnd.randint(-8, 22)))
    state = "LATE" if offset > 15 else ("EARLY" if offset < -10 else "ON_TIME")
    db.add(FacilityCheckin(shipment_id=sh.id, facility_id=fac.id, gate_in_ts=gate_in, yard_queue_enter_ts=gate_in, dock_in_ts=dock_in, unload_start_ts=unload_start, unload_end_ts=unload_end,
                           gate_out_ts=unload_end + timedelta(minutes=rnd.randint(8, 25)), arrival_state=state, queue_state="COMPLETED", actual_dock_id=dock.id, created_at=gate_in, updated_at=unload_end))
    made["checkins"] += 1


async def _delay_flow(db, rnd, counters, made, sh, drv, start, offset, car, fac, coord) -> None:
    reported = start - timedelta(minutes=rnd.randint(40, 200))
    cause = pick(rnd, CAUSES)
    declared = start + timedelta(minutes=offset + rnd.randint(-10, 15))
    db.add(EtaUpdate(shipment_id=sh.id, source_type="DRIVER_DECLARED", reported_by_driver_id=drv.id, declared_eta_ts=declared, confidence_code=rnd.choice(["MEDIUM", "MEDIUM", "HIGH", "LOW"]),
                     delay_reason_code=cause, note="demo-history", created_at=reported, updated_at=reported))
    made["delays"] += 1
    if rnd.random() < 0.55:
        return
    counters["thr"] += 1
    counters["exc"] += 1
    took_over = rnd.random() < 0.18
    thr = ChatThread(code=f"THH{counters['thr']:06d}", driver_id=drv.id, shipment_id=sh.id, opened_at=reported, closed_at=reported + timedelta(minutes=rnd.randint(8, 90)), thread_status="RESOLVED",
                     thread_intent="REPORT_DELAY", taken_over_by_user_id=coord.id if took_over else None, created_at=reported, updated_at=reported)
    db.add(thr)
    await db.flush()
    exc = DriverException(code=f"EXH{counters['exc']:06d}", shipment_id=sh.id, driver_id=drv.id, thread_id=thr.id, exception_type="BREAKDOWN" if cause == "BREAKDOWN" else "DELAY",
                          reported_at=reported, reported_delay_min=max(offset, 10), declared_eta_ts=declared, severity_code="HIGH" if sh.priority_code in ("HIGH", "CRITICAL") else "MEDIUM",
                          exception_status="RESOLVED", description=f"Demo history: driver reported a {cause.lower().replace('_', ' ')} delay", created_at=reported, updated_at=reported)
    db.add(exc)
    await db.flush()
    r = rnd.random()
    req_status = "approved" if r < 0.72 else "rejected" if r < 0.82 else "expired" if r < 0.94 else "escalated"  # history only: nothing left live in the inbox
    created = reported + timedelta(minutes=rnd.randint(2, 12))
    decided = None if req_status == "expired" else created + timedelta(minutes=int(rnd.lognormvariate(2.3, 0.7)) + 2)
    hold_id = None
    if req_status == "expired":
        slot = (await db.execute(select(AppointmentSlot.id).where(AppointmentSlot.facility_id == fac.id).limit(1))).scalar_one()
        hold = SlotHold(shipment_id=sh.id, slot_id=slot, status="expired", expires_at=created + timedelta(minutes=15), created_at=created, updated_at=created + timedelta(minutes=15))
        db.add(hold)
        await db.flush()
        hold_id = hold.id
    db.add(ApprovalRequest(shipment_id=sh.id, exception_id=exc.id, hold_id=hold_id, status=req_status, reason_code="DRIVER_DELAY", decided_by=coord.id if decided else None, decided_at=decided,
                           created_at=created, updated_at=decided or created))
    made["requests"] += 1
    if req_status == "escalated" or rnd.random() < 0.10:
        opened = created + timedelta(minutes=rnd.randint(1, 20))
        db.add(Escalation(shipment_id=sh.id, exception_id=exc.id, reason_code=pick(rnd, ESC_REASONS), handoff_record={"demo": True}, assigned_to=coord.id, status="resolved",
                          resolution="Handled by the desk (demo history)", closed_at=opened + timedelta(minutes=rnd.randint(6, 75)), created_at=opened, updated_at=opened))
        made["escalations"] += 1


if __name__ == "__main__":
    asyncio.run(main("--clear" in sys.argv, "--force" in sys.argv))
