from datetime import UTC, datetime, timedelta

from app.core.db import async_session_factory
from app.modules.appointments.models import Appointment
from tests.conftest import login

IST = timedelta(hours=5, minutes=30)
DAY = "2026-12-01"


def dock_body(fid, code="D1", **kw):
    return {"facility_id": str(fid), "dock_code": code, "dock_type": "STANDARD", "max_vehicle_weight_kg": 30000, **kw}


async def make_dock(client, world, code="D1", **kw):
    r = await client.post("/api/v1/docks", json=dock_body(world.facility_a.id, code, **kw))
    assert r.status_code == 201, r.text
    return r.json()


async def generate(client, world, dry_run=False, **kw):
    body = {"facility_id": str(world.facility_a.id), "date_from": DAY, "date_to": DAY, "dry_run": dry_run,
            "templates": [{"dock_type": "STANDARD", "start": "08:00", "end": "12:00", "length_min": 60}], **kw}
    return await client.post("/api/v1/slots/generate", json=body)


async def book(world, slot_id, status="CONFIRMED", shipment=None, code="APT-T"):
    async with async_session_factory() as db:
        db.add(Appointment(code=code, shipment_id=(shipment or world.shipment_a).id, slot_id=slot_id,
                           appointment_status=status, booking_source="PLANNER", booked_at=datetime.now(UTC)))
        await db.commit()


async def slots(client, world):
    r = await client.get("/api/v1/slots", params={"facility_id": str(world.facility_a.id), "date_from": DAY, "date_to": DAY})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- docks ----------
async def test_dock_crud_and_permissions(client, world):
    await login(client, "facility_planner")
    d = await make_dock(client, world, "d1", compatible_vehicle_type_codes=["VT1"])
    assert d["dock_code"] == "D1" and d["code"] == "FAC-A-D1"
    assert (await client.post("/api/v1/docks", json=dock_body(world.facility_a.id, "D1"))).status_code == 409
    assert (await client.post("/api/v1/docks", json=dock_body(world.facility_a.id, "D2", dock_type="WEIRD"))).status_code == 422
    assert (await client.post("/api/v1/docks", json=dock_body(world.facility_a.id, "D3", compatible_vehicle_type_codes=["NOPE"]))).status_code == 422
    r = await client.post("/api/v1/docks", json=dock_body(world.facility_a.id, "R1", dock_type="REEFER"))
    assert r.json()["supports_refrigerated"] is True
    p = await client.patch(f"/api/v1/docks/{d['id']}", json={"dock_status": "MAINTENANCE", "notes": "oil leak"})
    assert p.json()["dock_status"] == "MAINTENANCE"
    assert (await client.get("/api/v1/docks", params={"status": "MAINTENANCE"})).json()[0]["notes"] == "oil leak"


async def test_dock_scope_and_roles(client, world):
    await login(client, "facility_planner")
    assert (await client.post("/api/v1/docks", json=dock_body(world.facility_b.id))).status_code == 404
    client.cookies.clear()
    await login(client, "admin")
    assert (await client.get("/api/v1/docks")).status_code == 200
    assert (await client.post("/api/v1/docks", json=dock_body(world.facility_a.id))).status_code == 403
    for who in ("coordinator", "carrier_user"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post("/api/v1/docks", json=dock_body(world.facility_a.id))).status_code == (403)
    assert (await client.get("/api/v1/docks")).status_code in (200, 403)


async def test_retire_dock_blocked_by_future_booking(client, world):
    await login(client, "facility_planner")
    d = await make_dock(client, world)
    await generate(client, world)
    sl = await slots(client, world)
    await book(world, sl[0]["id"])
    r = await client.delete(f"/api/v1/docks/{d['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "FUTURE_BOOKINGS"
    d2 = await make_dock(client, world, "D2")
    assert (await client.delete(f"/api/v1/docks/{d2['id']}")).json()["dock_status"] == "INACTIVE"


# ---------- slot generation ----------
async def test_generate_dry_run_then_commit_and_overlap_skip(client, world):
    await login(client, "facility_planner")
    await make_dock(client, world, "D1")
    await make_dock(client, world, "D2")
    await make_dock(client, world, "H1", dock_type="HEAVY")
    dry = (await generate(client, world, dry_run=True)).json()
    assert dry == {"dry_run": True, "to_create": 8, "skipped_overlap": 0,
                   "per_dock": [{"dock_code": "D1", "count": 4}, {"dock_code": "D2", "count": 4}]}
    assert await slots(client, world) == []
    assert (await generate(client, world)).json()["to_create"] == 8
    again = (await generate(client, world)).json()
    assert again["to_create"] == 0 and again["skipped_overlap"] == 8
    sl = await slots(client, world)
    assert len(sl) == 8 and sl[0]["start"].startswith("2026-12-01T02:30")  # 08:00 IST


async def test_generate_validation_and_templates_for_heavy(client, world):
    await login(client, "facility_planner")
    await make_dock(client, world, "H1", dock_type="HEAVY")
    r = await generate(client, world, templates=[{"dock_type": "HEAVY", "start": "06:00", "end": "09:00", "length_min": 90}])
    assert r.json()["to_create"] == 2
    assert (await generate(client, world, templates=[{"dock_type": "HEAVY", "start": "09:00", "end": "06:00", "length_min": 90}])).status_code == 422
    assert (await generate(client, world, date_to="2027-03-01")).status_code == 422


async def test_slot_writes_forbidden_for_non_planners(client, world):
    for who in ("admin", "coordinator", "carrier_user"):
        client.cookies.clear()
        await login(client, who)
        assert (await generate(client, world)).status_code == 403


async def test_planner_cannot_generate_for_other_facility(client, world):
    await login(client, "facility_planner")
    r = await client.post("/api/v1/slots/generate", json={
        "facility_id": str(world.facility_b.id), "date_from": DAY, "date_to": DAY,
        "templates": [{"dock_type": "STANDARD", "start": "08:00", "end": "09:00", "length_min": 60}]})
    assert r.status_code == 404


async def test_exclusion_constraint_blocks_overlapping_slots(client, world):
    from sqlalchemy.exc import IntegrityError

    from app.modules.slots.models import AppointmentSlot

    await login(client, "facility_planner")
    d = await make_dock(client, world)
    await generate(client, world)
    async with async_session_factory() as db:
        s = AppointmentSlot(code="OVERLAP", facility_id=world.facility_a.id, dock_id=d["id"],
                            slot_start_ts=datetime(2026, 12, 1, 3, 0, tzinfo=UTC), slot_end_ts=datetime(2026, 12, 1, 4, 0, tzinfo=UTC))
        s.dock_id = __import__("uuid").UUID(d["id"])
        db.add(s)
        try:
            await db.commit()
            raised = False
        except IntegrityError:
            raised = True
    assert raised


# ---------- bulk status / copy day ----------
async def test_bulk_block_shows_affected_and_requires_force(client, world):
    await login(client, "facility_planner")
    await make_dock(client, world)
    await generate(client, world)
    sl = await slots(client, world)
    await book(world, sl[1]["id"])
    ids = [s["id"] for s in sl[:3]]
    dry = (await client.post("/api/v1/slots/bulk-status", json={"slot_ids": ids, "status": "BLOCKED", "reason": "audit", "dry_run": True})).json()
    assert dry["applied"] is False and [a["shipment_code"] for a in dry["affected_appointments"]] == ["SHP-A"]
    r = await client.post("/api/v1/slots/bulk-status", json={"slot_ids": ids, "status": "BLOCKED", "reason": "audit"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BOOKINGS_AFFECTED"
    ok = (await client.post("/api/v1/slots/bulk-status", json={"slot_ids": ids, "status": "BLOCKED", "reason": "audit", "force": True})).json()
    assert ok["applied"] is True and ok["updated"] == 3
    assert {s["slot_status"] for s in (await slots(client, world))[:3]} == {"BLOCKED"}
    assert (await client.post("/api/v1/slots/bulk-status", json={"slot_ids": ids, "status": "BLOCKED"})).status_code == 422
    reopen = (await client.post("/api/v1/slots/bulk-status", json={"slot_ids": ids, "status": "OPEN"})).json()
    assert reopen["updated"] == 3


async def test_copy_day(client, world):
    await login(client, "facility_planner")
    await make_dock(client, world)
    await generate(client, world)
    body = {"facility_id": str(world.facility_a.id), "from_date": DAY, "to_dates": ["2026-12-02", "2026-12-03"], "dry_run": True}
    assert (await client.post("/api/v1/slots/copy-day", json=body)).json()["to_create"] == 8
    assert (await client.post("/api/v1/slots/copy-day", json={**body, "dry_run": False})).json()["to_create"] == 8
    assert (await client.post("/api/v1/slots/copy-day", json={**body, "dry_run": False})).json() == {
        "dry_run": False, "to_create": 0, "skipped_overlap": 8}
    dates = (await client.get("/api/v1/slots/dates", params={"facility_id": str(world.facility_a.id)})).json()
    assert dates == [DAY, "2026-12-02", "2026-12-03"]
    empty = {**body, "from_date": "2027-01-01"}
    assert (await client.post("/api/v1/slots/copy-day", json=empty)).status_code == 422


# ---------- dock events ----------
async def test_dock_event_lists_affected_bookings_and_resolves(client, world):
    await login(client, "facility_planner")
    d = await make_dock(client, world)
    await generate(client, world)
    sl = await slots(client, world)
    await book(world, sl[1]["id"])  # 09:00-10:00 IST
    start = f"{DAY}T03:00:00Z"   # 08:30 IST
    prev = (await client.post("/api/v1/dock-events/preview", json={"dock_id": d["id"], "event_start_ts": start})).json()
    assert len(prev["affected_appointments"]) == 1
    e = await client.post("/api/v1/dock-events", json={"dock_id": d["id"], "event_type": "BREAKDOWN",
                                                      "event_start_ts": start, "reason": "hydraulic failure"})
    assert e.status_code == 201 and e.json()["affected_appointments"][0]["shipment_code"] == "SHP-A"
    assert e.json()["resolved"] is False and e.json()["affected_count"] == 1
    lst = (await client.get("/api/v1/dock-events", params={"facility_id": str(world.facility_a.id), "open_only": "true"})).json()
    assert len(lst) == 1
    assert (await client.post("/api/v1/dock-events", json={"dock_id": d["id"], "event_type": "BREAKDOWN",
                                                          "event_start_ts": start, "event_end_ts": f"{DAY}T02:00:00Z",
                                                          "reason": "bad range"})).status_code == 422


async def test_dock_event_scope(client, world):
    await login(client, "facility_planner")
    d = await make_dock(client, world)
    client.cookies.clear()
    await login(client, "carrier_user")
    assert (await client.post("/api/v1/dock-events", json={"dock_id": d["id"], "event_type": "MAINTENANCE",
                                                          "event_start_ts": f"{DAY}T03:00:00Z", "reason": "x y z"})).status_code == 403


# ---------- schedule grid ----------
async def test_schedule_grid_states(client, world):
    await login(client, "facility_planner")
    d1 = await make_dock(client, world, "D1")
    d2 = await make_dock(client, world, "D2")
    await generate(client, world)
    sl = {(s["dock_code"], s["start"][11:16]): s for s in await slots(client, world)}
    await book(world, sl[("D1", "02:30")]["id"], "COMPLETED", code="A1")
    await book(world, sl[("D1", "03:30")]["id"], "CONFIRMED", code="A2")
    await book(world, sl[("D1", "04:30")]["id"], "PENDING_CONFIRMATION", shipment=world.shipment_b, code="A3")
    await book(world, sl[("D1", "05:30")]["id"], "CANCELLED", code="A4")
    await client.post("/api/v1/slots/bulk-status", json={"slot_ids": [sl[("D2", "02:30")]["id"]], "status": "BLOCKED", "reason": "stock count"})
    await client.post("/api/v1/dock-events", json={"dock_id": d2["id"], "event_type": "MAINTENANCE",
                                                  "event_start_ts": f"{DAY}T03:30:00Z", "event_end_ts": f"{DAY}T04:30:00Z", "reason": "service"})
    await client.post("/api/v1/dock-events", json={"dock_id": d1["id"], "event_type": "CAPACITY_REDUCTION",
                                                  "event_start_ts": f"{DAY}T03:30:00Z", "event_end_ts": f"{DAY}T04:30:00Z", "reason": "half staff"})
    g = (await client.get("/api/v1/schedule", params={"facility_id": str(world.facility_a.id), "date": DAY})).json()
    assert g["facility"]["open_time"] == "06:00" and [d["dock_code"] for d in g["docks"]] == ["D1", "D2"]
    states = {(d["dock_code"], s["start"][11:16]): s for d in g["docks"] for s in d["slots"]}
    assert states[("D1", "02:30")]["state"] == "completed"
    assert states[("D1", "03:30")]["state"] == "reduced_capacity"      # event overrides a confirmed booking...
    assert states[("D1", "03:30")]["appointment"]["status"] == "CONFIRMED"  # ...but the booking is still shown
    assert states[("D1", "04:30")]["state"] == "pending_confirmation"
    assert states[("D1", "05:30")]["state"] == "open" and states[("D1", "05:30")]["history_state"] == "cancelled"
    assert states[("D2", "02:30")]["state"] == "blocked" and states[("D2", "02:30")]["block_reason"] == "stock count"
    assert states[("D2", "03:30")]["state"] == "maintenance"
    assert states[("D2", "05:30")]["state"] == "open"


async def test_schedule_scope_and_carrier_access(client, world):
    await login(client, "facility_planner")
    assert (await client.get("/api/v1/schedule", params={"facility_id": str(world.facility_b.id), "date": DAY})).status_code == 404
    client.cookies.clear()
    await login(client, "carrier_user")
    # carrier has day_schedule R but no facility scope: must see nothing of any facility
    assert (await client.get("/api/v1/schedule", params={"facility_id": str(world.facility_a.id), "date": DAY})).status_code == 404


async def test_slot_detail_includes_history(client, world):
    await login(client, "facility_planner")
    await make_dock(client, world)
    await generate(client, world)
    sl = await slots(client, world)
    await book(world, sl[0]["id"], "CANCELLED", code="OLD")
    await book(world, sl[0]["id"], "CONFIRMED", code="NEW", shipment=world.shipment_b)
    d = (await client.get(f"/api/v1/schedule/slots/{sl[0]['id']}")).json()
    assert d["appointment"]["code"] == "NEW" and d["shipment"]["code"] == "SHP-B"
    assert [h["status"] for h in d["history"]] == ["CANCELLED", "CONFIRMED"]
    assert d["eta"]["eta_source"] == "ORIGINAL_PLAN"


# ---------- rules ----------
async def test_rules_crud_validation_history(client, world):
    await login(client, "facility_planner")
    fid = world.facility_a.id
    types = (await client.get("/api/v1/facilities/rule-types")).json()
    assert {t["type"] for t in types} >= {"NO_SHOW_GRACE_MIN", "LAST_NEW_START_TIME"}
    body = {"rule_type": "NO_SHOW_GRACE_MIN", "rule_value": "25", "description": "Grace period", "effective_from": "2026-12-01"}
    r = await client.post(f"/api/v1/facilities/{fid}/rules", json=body)
    assert r.status_code == 201
    rid = r.json()["id"]
    assert (await client.post(f"/api/v1/facilities/{fid}/rules", json={**body, "rule_value": "abc"})).status_code == 422
    assert (await client.post(f"/api/v1/facilities/{fid}/rules", json={**body, "rule_type": "MADE_UP"})).status_code == 422
    assert (await client.post(f"/api/v1/facilities/{fid}/rules", json={**body, "rule_type": "LAST_NEW_START_TIME", "rule_value": "25:99"})).status_code == 422
    assert (await client.post(f"/api/v1/facilities/{fid}/rules", json={**body, "effective_to": "2026-11-01"})).status_code == 422
    u = await client.patch(f"/api/v1/facilities/{fid}/rules/{rid}", json={"rule_value": "40"})
    assert u.json()["rule_value"] == "40"
    h = (await client.get(f"/api/v1/facilities/{fid}/rules/{rid}/history")).json()["items"]
    assert [x["action"] for x in h] == ["insert", "update"] and h[1]["before"]["rule_value"] == "25"
    assert len((await client.get(f"/api/v1/facilities/{fid}/rules")).json()) == 1
    assert (await client.post(f"/api/v1/facilities/{world.facility_b.id}/rules", json=body)).status_code == 404


async def test_rules_roles(client, world):
    body = {"rule_type": "NO_SHOW_GRACE_MIN", "rule_value": "25", "description": "Grace period", "effective_from": "2026-12-01"}
    for who in ("admin", "coordinator", "carrier_user"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post(f"/api/v1/facilities/{world.facility_a.id}/rules", json=body)).status_code == 403


async def test_planner_can_manage_own_facility_contacts(client, world):
    await login(client, "facility_planner")
    fid = world.facility_a.id
    c = await client.post(f"/api/v1/facilities/{fid}/contacts", json={"contact_role": "Gate", "contact_name": "Ravi"})
    assert c.status_code == 201 and c.json()["missing_email"] is True
    assert (await client.post(f"/api/v1/facilities/{world.facility_b.id}/contacts",
                              json={"contact_role": "Gate", "contact_name": "X"})).status_code == 404
    assert (await client.post("/api/v1/facilities", json={"code": "ZZ", "facility_name": "Z", "city": "c", "state": "s",
                                                          "open_time": "06:00", "close_time": "10:00"})).status_code == 403
