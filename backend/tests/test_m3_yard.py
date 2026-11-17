"""Milestone 3 part B: pending confirmations, yard/gate lifecycle, inbound trucks, facility reports and home."""
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core import events
from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.docks.models import Dock, DockStatusEvent
from app.modules.drivers.models import Driver
from app.modules.eta.models import EtaUpdate
from app.modules.exceptions.models import DriverException
from app.modules.facilities.models import FacilityRule
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.vehicles.models import Vehicle
from app.modules.whatsapp.models import ChatThread
from tests.conftest import login

IST = ZoneInfo("Asia/Kolkata")


def now() -> datetime:
    return datetime.now(UTC)


def noon_today() -> datetime:
    return datetime.combine(datetime.now(IST).date(), time(12), tzinfo=IST).astimezone(UTC)


def local_date(ts: datetime) -> str:
    return ts.astimezone(IST).date().isoformat()


async def as_(client, who):
    client.cookies.clear()
    await login(client, who)


# ----------------------------------------------------------------------- ORM helpers
async def mk_dock(fac, dock_code, dock_type="STANDARD", max_kg=40000, status="ACTIVE", refrigerated=False):
    async with async_session_factory() as db:
        d = Dock(code=f"{fac.code}-{dock_code}", facility_id=fac.id, dock_code=dock_code, dock_type=dock_type,
                 max_vehicle_weight_kg=max_kg, dock_status=status, supports_refrigerated=refrigerated)
        db.add(d)
        await db.commit()
        return d


async def mk_slot(fac, dock, start, minutes=60, status="OPEN"):
    async with async_session_factory() as db:
        s = AppointmentSlot(code=f"S{int(start.timestamp())}{dock.dock_code}{dock.id.hex[:6]}"[:32], facility_id=fac.id, dock_id=dock.id,
                            slot_start_ts=start, slot_end_ts=start + timedelta(minutes=minutes), slot_status=status)
        db.add(s)
        await db.commit()
        return s


async def mk_appt(ship, slot, status="CONFIRMED", booked_at=None, is_current=True):
    async with async_session_factory() as db:
        a = Appointment(code="APT" + uuid.uuid4().hex[:8], shipment_id=ship.id, slot_id=slot.id,
                        appointment_status=status, booking_source="PLANNER", is_current=is_current,
                        booked_at=booked_at or now())
        db.add(a)
        await db.commit()
        return a


async def mk_ship(world, fac=None, tag=None, status="IN_TRANSIT", **kw):
    tag = tag or uuid.uuid4().hex[:6]
    fac = fac or world.facility_a
    async with async_session_factory() as db:
        drv = (await db.execute(select(Driver).where(Driver.code == "DRV-A"))).scalar_one()
        veh = (await db.execute(select(Vehicle).where(Vehicle.code == "VEH-A"))).scalar_one()
        fields = dict(code=f"SHX-{tag}", order_reference=f"ORD-{tag}", carrier_id=world.carrier_a.id, driver_id=drv.id,
                      vehicle_id=veh.id, origin_name="O", origin_city="Delhi", destination_facility_id=fac.id,
                      customer_name="C", product_category="Goods", load_weight_kg=5000, planned_departure_ts=now(),
                      original_eta_ts=now(), expected_unload_min=60, current_status=status, offer_status="accepted")
        fields.update(kw)
        s = Shipment(**fields)
        db.add(s)
        await db.commit()
        return s


async def mk_ships(world, *tags):
    return [await mk_ship(world, tag=t) for t in tags]


async def reload(model, pk):
    async with async_session_factory() as db:
        return await db.get(model, pk)


async def checkin_of(ship):
    async with async_session_factory() as db:
        return (await db.execute(select(FacilityCheckin).where(FacilityCheckin.shipment_id == ship.id))).scalar_one()


async def cancel_seed_shipments(world):
    async with async_session_factory() as db:
        for sid in (world.shipment_a.id, world.shipment_b.id):
            (await db.get(Shipment, sid)).current_status = "CANCELLED"
        await db.commit()


# ----------------------------------------------------------------------- pending confirmations
async def test_pending_list_reason_scope_and_permissions(client, world):
    d1 = await mk_dock(world.facility_a, "D1")
    db_ = await mk_dock(world.facility_b, "D1")
    async with async_session_factory() as db:
        db.add(FacilityRule(facility_id=world.facility_a.id, rule_type="LAST_NEW_START_TIME", rule_value="21:00",
                            description="No new starts after 21:00", effective_from=date(2026, 1, 1)))
        await db.commit()
    day = datetime(2026, 12, 1, tzinfo=IST)
    late_slot = await mk_slot(world.facility_a, d1, day.replace(hour=22).astimezone(UTC))
    day_slot = await mk_slot(world.facility_a, d1, day.replace(hour=10).astimezone(UTC))
    b_slot = await mk_slot(world.facility_b, db_, day.replace(hour=10).astimezone(UTC))
    s2 = await mk_ship(world, tag="P2")
    booked = now() - timedelta(minutes=5)
    await mk_appt(world.shipment_a, late_slot, "PENDING_CONFIRMATION", booked)
    await mk_appt(s2, day_slot, "PENDING_CONFIRMATION", booked)
    await mk_appt(world.shipment_b, b_slot, "PENDING_CONFIRMATION", booked)

    await as_(client, "facility_planner")
    rows = (await client.get("/api/v1/appointments/pending")).json()
    assert len(rows) == 2 and {r["dock_code"] for r in rows} == {"D1"}
    by_ship = {r["shipment_code"]: r for r in rows}
    assert by_ship["SHP-A"]["reason"] == "STARTS_AFTER_LAST_START" and by_ship["SHX-P2"]["reason"] == "NEEDS_CONFIRMATION"
    r = by_ship["SHP-A"]
    assert r["carrier_name"] == "Carrier A" and r["driver_name"] == "Driver A" and r["priority_code"] == "NORMAL"
    exp = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00"))
    assert abs((exp - datetime.fromisoformat(r["booked_at"].replace("Z", "+00:00"))).total_seconds() - 1800) < 1
    assert (await client.get("/api/v1/appointments/pending", params={"facility_id": str(world.facility_a.id)})).status_code == 200
    assert (await client.get("/api/v1/appointments/pending", params={"facility_id": str(world.facility_b.id)})).status_code == 404

    await as_(client, "coordinator")
    assert len((await client.get("/api/v1/appointments/pending")).json()) == 3
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/appointments/pending")).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/v1/appointments/pending")).status_code == 401


async def test_confirm_and_reject_rules(client, world):
    da, dbk = await mk_dock(world.facility_a, "D1"), await mk_dock(world.facility_b, "D1")
    t = now() + timedelta(days=2)
    a1 = await mk_appt(world.shipment_a, await mk_slot(world.facility_a, da, t), "PENDING_CONFIRMATION")
    s2 = await mk_ship(world, tag="C2")
    slot2 = await mk_slot(world.facility_a, da, t + timedelta(hours=2))
    a2 = await mk_appt(s2, slot2, "PENDING_CONFIRMATION")
    b1 = await mk_appt(world.shipment_b, await mk_slot(world.facility_b, dbk, t), "PENDING_CONFIRMATION")

    await as_(client, "coordinator")  # read-only on day_schedule
    assert (await client.post(f"/api/v1/appointments/{a1.id}/confirm")).status_code == 403
    assert (await client.post(f"/api/v1/appointments/{a1.id}/reject", json={"reason": "no way"})).status_code == 403
    await as_(client, "carrier_user")
    assert (await client.post(f"/api/v1/appointments/{a1.id}/confirm")).status_code == 403

    await as_(client, "facility_planner")
    assert (await client.post(f"/api/v1/appointments/{b1.id}/confirm")).status_code == 404  # other facility
    assert (await client.post(f"/api/v1/appointments/{uuid.uuid4()}/confirm")).status_code == 404
    ok = await client.post(f"/api/v1/appointments/{a1.id}/confirm")
    assert ok.status_code == 200 and ok.json()["appointment_status"] == "CONFIRMED"
    assert (await reload(Appointment, a1.id)).confirmed_at is not None
    assert (await client.post(f"/api/v1/appointments/{a1.id}/confirm")).status_code == 409
    assert (await client.post(f"/api/v1/appointments/{a1.id}/reject", json={"reason": "late"})).status_code == 409

    assert (await client.post(f"/api/v1/appointments/{a2.id}/reject", json={"reason": "x"})).status_code == 422
    rej = await client.post(f"/api/v1/appointments/{a2.id}/reject", json={"reason": "Dock needed for maintenance"})
    assert rej.status_code == 200 and rej.json()["appointment_status"] == "REJECTED" and rej.json()["is_current"] is False
    stored = await reload(Appointment, a2.id)
    assert stored.cancellation_reason == "Dock needed for maintenance"
    await mk_appt(await mk_ship(world, tag="C4"), slot2, "CONFIRMED")  # slot is free again (partial unique index)
    pend = (await client.get("/api/v1/appointments/pending")).json()
    assert pend == []


async def test_confirm_publishes_schedule_event(client, world):
    da = await mk_dock(world.facility_a, "D1")
    a1 = await mk_appt(world.shipment_a, await mk_slot(world.facility_a, da, now() + timedelta(days=2)),
                       "PENDING_CONFIRMATION")
    redis = get_redis()
    try:
        await redis.delete(events.STREAM)
        await as_(client, "facility_planner")
        assert (await client.post(f"/api/v1/appointments/{a1.id}/confirm")).status_code == 200
        entries = await redis.xrange(events.STREAM)
        assert entries and entries[-1][1]["type"] == "schedule.changed"
        assert entries[-1][1]["facility_id"] == str(world.facility_a.id)
    finally:
        await redis.delete(events.STREAM)
        await redis.aclose()


# ----------------------------------------------------------------------- check-in
async def test_check_in_classification_and_queue_positions(client, world):
    d1 = await mk_dock(world.facility_a, "D1")
    early = await mk_slot(world.facility_a, d1, now() + timedelta(hours=3))
    on_time = await mk_slot(world.facility_a, d1, now() + timedelta(minutes=5))
    late = await mk_slot(world.facility_a, d1, now() - timedelta(minutes=90))
    s_early, s_late, s_none = await mk_ships(world, "E", "L", "N")
    await mk_appt(world.shipment_a, on_time)
    await mk_appt(s_early, early)
    await mk_appt(s_late, late)
    await as_(client, "facility_planner")

    r1 = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(world.shipment_a.id)}))
    assert r1.status_code == 201
    assert (r1.json()["arrival_state"], r1.json()["queue_state"], r1.json()["queue_position"]) == ("ON_TIME", "CALLED_TO_DOCK", 1)
    assert (await reload(Shipment, world.shipment_a.id)).current_status == "AT_GATE"
    r2 = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s_early.id)})).json()
    assert (r2["arrival_state"], r2["queue_state"], r2["queue_position"]) == ("EARLY", "WAITING_EARLY", 2)
    assert (await reload(Shipment, s_early.id)).current_status == "WAITING"
    r3 = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s_late.id)})).json()
    assert (r3["arrival_state"], r3["queue_state"], r3["queue_position"]) == ("LATE", "WAITING_LATE", 3)
    r4 = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s_none.id)})).json()
    assert (r4["arrival_state"], r4["queue_state"], r4["queue_position"]) == (None, "WAITING_DOCK_UNAVAILABLE", 4)
    assert r4["appointment_id"] is None and r1.json()["planned_dock_code"] == "D1"

    dup = await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s_none.id)})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "ALREADY_CHECKED_IN"


async def test_check_in_rejections_and_scope(client, world):
    await as_(client, "facility_planner")
    assert (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(world.shipment_b.id)})).status_code == 404
    assert (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(uuid.uuid4())})).status_code == 404
    cancelled = await mk_ship(world, tag="CX", status="CANCELLED")
    assert (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(cancelled.id)})).status_code == 409
    for who in ("coordinator", "carrier_user", "admin"):
        await as_(client, who)
        assert (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(world.shipment_a.id)})).status_code == 403


# ----------------------------------------------------------------------- dock assignment
async def test_assign_dock_compatibility_busy_and_foreign_dock(client, world):
    std = await mk_dock(world.facility_a, "D1")
    reefer = await mk_dock(world.facility_a, "R1", "REEFER", refrigerated=True)
    other = await mk_dock(world.facility_b, "D9")
    out_of_service = await mk_dock(world.facility_a, "D8", status="OUT_OF_SERVICE")
    cold = await mk_ship(world, tag="CLD", required_dock_type="REEFER", temperature_control_required=True)
    heavy = await mk_ship(world, tag="HVY", load_weight_kg=30000)
    plain = await mk_ship(world, tag="PLN")
    async with async_session_factory() as db:
        db.add(FacilityRule(facility_id=world.facility_a.id, rule_type="HEAVY_DOCK_REQUIRED_KG", rule_value="25000",
                            description="Heavy loads", effective_from=date(2026, 1, 1)))
        await db.commit()
    await as_(client, "facility_planner")
    ids = {}
    for s in (cold, heavy, plain, world.shipment_a):
        ids[s.code] = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s.id)})).json()["checkin_id"]

    bad = await client.post(f"/api/v1/yard/{ids['SHX-CLD']}/assign-dock", json={"dock_id": str(std.id)})
    assert bad.status_code == 422 and "NEEDS_REEFER_DOCK" in bad.json()["error"]["details"]["problems"]
    assert "NEEDS_REFRIGERATED_DOCK" in bad.json()["error"]["details"]["problems"]
    hv = await client.post(f"/api/v1/yard/{ids['SHX-HVY']}/assign-dock", json={"dock_id": str(std.id)})
    assert hv.status_code == 422 and "NEEDS_HEAVY_DOCK" in hv.json()["error"]["details"]["problems"]
    assert (await client.post(f"/api/v1/yard/{ids['SHX-PLN']}/assign-dock",
                              json={"dock_id": str(out_of_service.id)})).json()["error"]["details"]["problems"] == ["DOCK_NOT_ACTIVE"]
    assert (await client.post(f"/api/v1/yard/{ids['SHX-PLN']}/assign-dock", json={"dock_id": str(other.id)})).status_code == 422
    assert (await client.post(f"/api/v1/yard/{uuid.uuid4()}/assign-dock", json={"dock_id": str(std.id)})).status_code == 404

    ok = await client.post(f"/api/v1/yard/{ids['SHX-CLD']}/assign-dock", json={"dock_id": str(reefer.id)})
    assert ok.status_code == 200 and ok.json()["queue_state"] == "IN_DOCK" and ok.json()["actual_dock_code"] == "R1"
    assert (await reload(Shipment, cold.id)).current_status == "IN_DOCK"
    assert ok.json()["dock_mismatch"] is False  # no appointment, so nothing to mismatch against
    first = await client.post(f"/api/v1/yard/{ids['SHX-PLN']}/assign-dock", json={"dock_id": str(std.id)})
    assert first.status_code == 200
    busy = await client.post(f"/api/v1/yard/{ids['SHP-A']}/assign-dock", json={"dock_id": str(std.id)})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "DOCK_BUSY"
    again = await client.post(f"/api/v1/yard/{ids['SHX-PLN']}/assign-dock", json={"dock_id": str(std.id)})
    assert again.status_code == 409  # already at a dock

    await as_(client, "coordinator")
    assert (await client.post(f"/api/v1/yard/{ids['SHP-A']}/assign-dock", json={"dock_id": str(std.id)})).status_code == 403


async def test_dock_mismatch_flag_and_yard_scope(client, world):
    d1, d2 = await mk_dock(world.facility_a, "D1"), await mk_dock(world.facility_a, "D2")
    slot = await mk_slot(world.facility_a, d1, now() + timedelta(minutes=5))
    await mk_appt(world.shipment_a, slot)
    await as_(client, "facility_planner")
    cid = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(world.shipment_a.id)})).json()["checkin_id"]
    row = (await client.post(f"/api/v1/yard/{cid}/assign-dock", json={"dock_id": str(d2.id)})).json()
    assert row["planned_dock_code"] == "D1" and row["actual_dock_code"] == "D2" and row["dock_mismatch"] is True
    # another facility's planner cannot touch this check-in
    other_planner = await mk_planner_for(world.facility_b)
    client.cookies.clear()
    r = await client.post("/api/v1/auth/login", json={"email": other_planner, "password": "CorrectHorse-Battery9"})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert (await client.post(f"/api/v1/yard/{cid}/start-unload")).status_code == 404
    assert (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_a.id)})).status_code == 404


async def mk_planner_for(fac) -> str:
    from app.modules.users.models import User, UserScope
    from tests.conftest import _HASH

    email = f"planner-{fac.code.lower()}@test.io"
    async with async_session_factory() as db:
        u = User(email=email, full_name="Planner B", role="facility_planner", status="active", password_hash=_HASH)
        db.add(u)
        await db.flush()
        db.add(UserScope(user_id=u.id, facility_id=fac.id))
        await db.commit()
    return email


# ----------------------------------------------------------------------- unload / gate out
async def test_unload_flow_overrun_and_detention(client, world):
    d1 = await mk_dock(world.facility_a, "D1")
    slot = await mk_slot(world.facility_a, d1, now() + timedelta(minutes=5))
    appt = await mk_appt(world.shipment_a, slot)
    await as_(client, "facility_planner")
    cid = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(world.shipment_a.id)})).json()["checkin_id"]
    assert (await client.post(f"/api/v1/yard/{cid}/start-unload")).status_code == 409  # not at a dock yet
    assert (await client.post(f"/api/v1/yard/{cid}/finish-unload")).status_code == 409
    assert (await client.post(f"/api/v1/yard/{cid}/gate-out")).status_code == 409
    assert (await client.post(f"/api/v1/yard/{cid}/assign-dock", json={"dock_id": str(d1.id)})).status_code == 200
    started = await client.post(f"/api/v1/yard/{cid}/start-unload")
    assert started.status_code == 200 and started.json()["unload_start_ts"]
    assert (await reload(Appointment, appt.id)).appointment_status == "IN_PROGRESS"
    assert (await client.post(f"/api/v1/yard/{cid}/start-unload")).status_code == 409

    async with async_session_factory() as db:  # make the unload look 90 min long after 30 min in the yard
        ck = await db.get(FacilityCheckin, uuid.UUID(cid))
        ck.gate_in_ts, ck.unload_start_ts = now() - timedelta(minutes=120), now() - timedelta(minutes=90)
        await db.commit()
    fin = await client.post(f"/api/v1/yard/{cid}/finish-unload")
    body = fin.json()
    assert fin.status_code == 200 and body["queue_state"] == "COMPLETED"
    assert abs(body["unload_min"] - 90) <= 1 and abs(body["overrun_min"] - 30) <= 1
    assert abs(body["detention_min"] - 30) <= 1
    assert (await reload(Appointment, appt.id)).appointment_status == "COMPLETED"
    assert (await reload(Shipment, world.shipment_a.id)).current_status == "COMPLETED"
    assert (await client.post(f"/api/v1/yard/{cid}/finish-unload")).status_code == 409
    out = await client.post(f"/api/v1/yard/{cid}/gate-out")
    assert out.status_code == 200
    assert (await checkin_of(world.shipment_a)).gate_out_ts is not None
    assert (await client.post(f"/api/v1/yard/{cid}/gate-out")).status_code == 409

    await as_(client, "coordinator")
    for action in ("start-unload", "finish-unload", "gate-out"):
        assert (await client.post(f"/api/v1/yard/{cid}/{action}")).status_code == 403


# ----------------------------------------------------------------------- no-show
async def test_no_show_after_grace_frees_capacity(client, world):
    d1 = await mk_dock(world.facility_a, "D1")
    old = await mk_slot(world.facility_a, d1, now() - timedelta(hours=2))
    inside_grace = await mk_slot(world.facility_a, d1, now() - timedelta(minutes=10))
    future = await mk_slot(world.facility_a, d1, now() + timedelta(hours=5))
    s2, s3 = await mk_ship(world, tag="NS2"), await mk_ship(world, tag="NS3")
    a_old = await mk_appt(world.shipment_a, old)
    a_grace = await mk_appt(s2, inside_grace)
    a_future = await mk_appt(s3, future)
    await as_(client, "facility_planner")
    for a in (a_grace, a_future):
        r = await client.post("/api/v1/yard/no-show", json={"appointment_id": str(a.id)})
        assert r.status_code == 409 and r.json()["error"]["code"] == "GRACE_NOT_ELAPSED"
    ok = await client.post("/api/v1/yard/no-show", json={"appointment_id": str(a_old.id)})
    assert ok.status_code == 200 and ok.json()["appointment_status"] == "NO_SHOW" and ok.json()["is_current"] is False
    assert (await client.post("/api/v1/yard/no-show", json={"appointment_id": str(a_old.id)})).status_code == 409
    await mk_appt(await mk_ship(world, tag="NS4"), old)  # capacity freed: the slot can be booked again
    assert (await client.post("/api/v1/yard/no-show", json={"appointment_id": str(uuid.uuid4())})).status_code == 404
    other = await mk_planner_for(world.facility_b)
    client.cookies.clear()
    await client.post("/api/v1/auth/login", json={"email": other, "password": "CorrectHorse-Battery9"})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert (await client.post("/api/v1/yard/no-show", json={"appointment_id": str(a_grace.id)})).status_code == 404
    await as_(client, "coordinator")
    assert (await client.post("/api/v1/yard/no-show", json={"appointment_id": str(a_grace.id)})).status_code == 403


async def test_no_show_respects_facility_grace_rule_and_marks_checkin(client, world):
    d1 = await mk_dock(world.facility_a, "D1")
    slot = await mk_slot(world.facility_a, d1, now() - timedelta(minutes=45))
    appt = await mk_appt(world.shipment_a, slot)
    async with async_session_factory() as db:
        db.add(FacilityRule(facility_id=world.facility_a.id, rule_type="NO_SHOW_GRACE_MIN", rule_value="60",
                            description="Wait an hour", effective_from=date(2026, 1, 1)))
        await db.commit()
    await as_(client, "facility_planner")
    r = await client.post("/api/v1/yard/no-show", json={"appointment_id": str(appt.id)})
    assert r.status_code == 409 and r.json()["error"]["details"]["grace_minutes"] == 60


# ----------------------------------------------------------------------- yard buckets
async def test_yard_buckets(client, world):
    d1, d2 = await mk_dock(world.facility_a, "D1"), await mk_dock(world.facility_a, "D2")
    base = noon_today()
    expected_slot = await mk_slot(world.facility_a, d2, base)
    s_wait, s_dock, s_done, s_exp = await mk_ships(world, "W", "D", "F", "X")
    await mk_appt(s_exp, expected_slot)
    await as_(client, "facility_planner")
    ck = {}
    for s in (s_wait, s_dock, s_done):
        ck[s.code] = (await client.post("/api/v1/yard/check-in", json={"shipment_id": str(s.id)})).json()["checkin_id"]
    await client.post(f"/api/v1/yard/{ck['SHX-D']}/assign-dock", json={"dock_id": str(d1.id)})
    await client.post(f"/api/v1/yard/{ck['SHX-F']}/assign-dock", json={"dock_id": str(d2.id)})
    await client.post(f"/api/v1/yard/{ck['SHX-F']}/start-unload")
    await client.post(f"/api/v1/yard/{ck['SHX-F']}/finish-unload")

    y = (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_a.id),
                                                  "date": local_date(base)})).json()
    assert [r["shipment_code"] for r in y["queue"]] == ["SHX-W"] and y["queue"][0]["queue_position"] == 1
    assert [r["shipment_code"] for r in y["in_dock"]] == ["SHX-D"] and y["in_dock"][0]["actual_dock_code"] == "D1"
    assert [r["shipment_code"] for r in y["done"]] == ["SHX-F"] and y["done"][0]["overrun_min"] is not None
    assert [r["shipment_code"] for r in y["expected"]] == ["SHX-X"] and y["expected"][0]["checkin_id"] is None
    assert y["expected"][0]["planned_dock_code"] == "D2" and y["expected"][0]["load"] == "ANY"
    assert y["expected"][0]["appointment_status"] == "CONFIRMED" and y["expected"][0]["carrier_name"] == "Carrier A"

    empty = (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_a.id), "date": "2020-01-01"})).json()
    assert empty["expected"] == [] and empty["done"] == [] and len(empty["queue"]) == 1  # queue is live, not per-day

    await as_(client, "coordinator")
    assert (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_b.id)})).status_code == 200
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_a.id)})).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/v1/yard", params={"facility_id": str(world.facility_a.id)})).status_code == 401
    assert (await client.get("/api/v1/yard")).status_code == 401


# ----------------------------------------------------------------------- inbound
async def test_inbound_flags_and_filters(client, world):
    await cancel_seed_shipments(world)
    base = noon_today()
    docks = [await mk_dock(world.facility_a, f"D{i}") for i in range(1, 5)]
    late = await mk_ship(world, tag="LATE", original_eta_ts=base + timedelta(minutes=20))
    close = await mk_ship(world, tag="CLOSE", original_eta_ts=base - timedelta(minutes=10))
    safe = await mk_ship(world, tag="SAFE", original_eta_ts=base - timedelta(hours=3))
    await mk_appt(late, await mk_slot(world.facility_a, docks[0], base))
    await mk_appt(close, await mk_slot(world.facility_a, docks[1], base))
    await mk_appt(safe, await mk_slot(world.facility_a, docks[2], base))
    no_appt = await mk_ship(world, tag="NOAPT", original_eta_ts=base + timedelta(hours=1))
    vague = await mk_ship(world, tag="VAGUE", original_eta_ts=base - timedelta(hours=5))
    await mk_appt(vague, await mk_slot(world.facility_a, docks[3], base))
    async with async_session_factory() as db:
        db.add(EtaUpdate(shipment_id=vague.id, source_type="DRIVER_DECLARED", declared_eta_ts=base - timedelta(hours=4),
                         confidence_code="LOW"))
        await db.commit()
    await mk_ship(world, tag="NEXTWEEK", original_eta_ts=base + timedelta(days=5))
    await mk_ship(world, tag="DONE", status="COMPLETED", original_eta_ts=base)
    await mk_ship(world, tag="OFFER", driver_id=None, vehicle_id=None, status="PLANNED", original_eta_ts=base)

    await as_(client, "facility_planner")
    rows = (await client.get("/api/v1/inbound", params={"facility_id": str(world.facility_a.id),
                                                        "date": local_date(base)})).json()
    by = {r["shipment_code"]: r for r in rows}
    assert set(by) == {"SHX-LATE", "SHX-CLOSE", "SHX-SAFE", "SHX-NOAPT", "SHX-VAGUE"}
    assert (by["SHX-LATE"]["late"], by["SHX-LATE"]["at_risk"]) == (True, False)
    assert (by["SHX-CLOSE"]["late"], by["SHX-CLOSE"]["at_risk"]) == (False, True)
    assert (by["SHX-SAFE"]["late"], by["SHX-SAFE"]["at_risk"]) == (False, False)
    assert (by["SHX-NOAPT"]["late"], by["SHX-NOAPT"]["at_risk"], by["SHX-NOAPT"]["slot_code"]) == (False, True, None)
    assert by["SHX-VAGUE"]["at_risk"] is True and by["SHX-VAGUE"]["eta_confidence"] == "LOW"
    assert by["SHX-VAGUE"]["eta_source"] == "DRIVER_DECLARED" and by["SHX-LATE"]["eta_source"] == "ORIGINAL_PLAN"
    assert by["SHX-LATE"]["dock_code"] == "D1" and by["SHX-LATE"]["carrier_name"] == "Carrier A"
    assert [r["eta_ts"] for r in rows] == sorted(r["eta_ts"] for r in rows)
    next_week = (await client.get("/api/v1/inbound", params={"facility_id": str(world.facility_a.id),
                                                             "date": local_date(base + timedelta(days=5))})).json()
    assert [r["shipment_code"] for r in next_week] == ["SHX-NEXTWEEK"]

    assert (await client.get("/api/v1/inbound", params={"facility_id": str(world.facility_b.id)})).status_code == 404
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/inbound", params={"facility_id": str(world.facility_a.id)})).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/v1/inbound", params={"facility_id": str(world.facility_a.id)})).status_code == 401


# ----------------------------------------------------------------------- reports and home
async def _report_world(world):
    base = noon_today()
    d1 = await mk_dock(world.facility_a, "D1")
    slots = [await mk_slot(world.facility_a, d1, base + timedelta(hours=i)) for i in range(3)]
    blocked = await mk_slot(world.facility_a, d1, base + timedelta(hours=3), status="BLOCKED")
    s1, s2, s3 = await mk_ships(world, "R1", "R2", "R3")
    await mk_appt(s1, slots[0], "COMPLETED")
    await mk_appt(s2, slots[1], "CONFIRMED")
    await mk_appt(s3, slots[2], "NO_SHOW", is_current=False)
    async with async_session_factory() as db:
        db.add(FacilityCheckin(shipment_id=s1.id, facility_id=world.facility_a.id, gate_in_ts=base,
                               unload_start_ts=base + timedelta(minutes=30), unload_end_ts=base + timedelta(minutes=120),
                               queue_state="COMPLETED", arrival_state="ON_TIME", actual_dock_id=d1.id))
        db.add(FacilityCheckin(shipment_id=s2.id, facility_id=world.facility_a.id, gate_in_ts=base + timedelta(hours=1),
                               queue_state="WAITING_LATE", queue_position=1))
        await db.commit()
    return base, d1, blocked


async def test_reports(client, world):
    base, _, _ = await _report_world(world)
    day = local_date(base)
    params = {"facility_id": str(world.facility_a.id), "date_from": day, "date_to": day}
    await as_(client, "facility_planner")

    util = (await client.get("/api/v1/reports/facility", params={**params, "kind": "utilisation"})).json()
    assert util["columns"] == ["date", "dock_code", "available_min", "booked_min", "utilisation_pct"]
    assert util["rows"] == [{"date": day, "dock_code": "D1", "available_min": 120, "booked_min": 120,
                             "utilisation_pct": 100.0}] or util["rows"][0]["booked_min"] == 120
    # 3 OPEN slots, the NO_SHOW one is not booked: 180 available, 120 booked
    assert util["rows"][0]["available_min"] == 180 and util["rows"][0]["utilisation_pct"] == 66.7

    det = (await client.get("/api/v1/reports/facility", params={**params, "kind": "detention"})).json()
    assert [(r["shipment_code"], r["detention_min"]) for r in det["rows"]] == [("SHX-R1", 30)]
    ovr = (await client.get("/api/v1/reports/facility", params={**params, "kind": "overrun"})).json()
    assert [(r["shipment_code"], r["expected_min"], r["actual_min"], r["overrun_min"]) for r in ovr["rows"]] == [
        ("SHX-R1", 60, 90, 30)]
    ns = (await client.get("/api/v1/reports/facility", params={**params, "kind": "noshow"})).json()
    assert ns["rows"] == [{"date": day, "no_shows": 1, "scheduled": 3, "no_show_rate_pct": 33.3}]

    csv = await client.get("/api/v1/reports/facility/export.csv", params={**params, "kind": "overrun"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0] == "date,shipment_code,carrier_name,expected_min,actual_min,overrun_min"
    assert "SHX-R1" in csv.text

    assert (await client.get("/api/v1/reports/facility", params={**params, "kind": "nope"})).status_code == 422
    assert (await client.get("/api/v1/reports/facility", params={**params, "kind": "noshow",
                                                                 "date_to": "2099-01-01"})).status_code == 422
    assert (await client.get("/api/v1/reports/facility", params={**params, "kind": "noshow",
                                                                 "date_from": "2099-01-01"})).status_code == 422
    other = {**params, "facility_id": str(world.facility_b.id), "kind": "noshow"}
    assert (await client.get("/api/v1/reports/facility", params=other)).status_code == 404

    await as_(client, "coordinator")
    assert (await client.get("/api/v1/reports/facility", params={**other})).status_code == 200
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/reports/facility", params={**params, "kind": "noshow"})).status_code == 403
    assert (await client.get("/api/v1/reports/facility/export.csv", params={**params, "kind": "noshow"})).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/v1/reports/facility", params={**params, "kind": "noshow"})).status_code == 401


async def test_facility_home(client, world):
    base, d1, _ = await _report_world(world)
    await mk_dock(world.facility_a, "D2", status="MAINTENANCE")
    async with async_session_factory() as db:
        db.add(DockStatusEvent(dock_id=d1.id, event_type="BREAKDOWN", event_start_ts=now() - timedelta(hours=1),
                               event_end_ts=None, reason="Door jammed"))
        thread = ChatThread(code="THR-X", driver_id=(await db.execute(select(Driver.id).where(Driver.code == "DRV-A"))).scalar_one(),
                            shipment_id=world.shipment_a.id, opened_at=now(), thread_status="OPEN", thread_intent="REPORT_DELAY")
        db.add(thread)
        await db.flush()
        db.add(DriverException(code="EXC-X", shipment_id=world.shipment_a.id, driver_id=thread.driver_id,
                               thread_id=thread.id, exception_type="DELAY", reported_at=now(),
                               exception_status="OPEN", description="Stuck in traffic"))
        db.add(DriverException(code="EXC-Y", shipment_id=world.shipment_a.id, driver_id=thread.driver_id,
                               thread_id=thread.id, exception_type="DELAY", reported_at=now(),
                               exception_status="RESOLVED", description="Done"))
        await db.commit()
    s_pend = await mk_ship(world, tag="PEND")
    da = await mk_dock(world.facility_a, "D3")
    await mk_appt(s_pend, await mk_slot(world.facility_a, da, now() + timedelta(days=3)), "PENDING_CONFIRMATION")

    await as_(client, "facility_planner")
    r = await client.get("/api/v1/analytics/facility-home", params={"facility_id": str(world.facility_a.id)})
    assert r.status_code == 200
    h = r.json()
    assert h["date"] == local_date(now()) and h["active_holds"] == 0
    assert h["open_exceptions"] == 1 and h["pending_confirmations"] == 1 and h["in_yard_count"] == 1
    assert h["dock_status"] == {"active": 2, "maintenance": 1, "out_of_service": 0, "inactive": 0, "events_open": 1}
    assert h["utilisation_pct"] == 66.7 and isinstance(h["inbound_count"], int)

    assert (await client.get("/api/v1/analytics/facility-home", params={"facility_id": str(world.facility_b.id)})).status_code == 404
    await as_(client, "coordinator")
    assert (await client.get("/api/v1/analytics/facility-home", params={"facility_id": str(world.facility_b.id)})).status_code == 200
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/analytics/facility-home", params={"facility_id": str(world.facility_a.id)})).status_code == 403
    client.cookies.clear()
    assert (await client.get("/api/v1/analytics/facility-home", params={"facility_id": str(world.facility_a.id)})).status_code == 401
