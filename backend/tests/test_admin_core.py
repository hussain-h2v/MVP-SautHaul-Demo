import io
import uuid

from tests.conftest import login

FAC = {"code": "fac-new", "facility_name": "New DC", "city": "Pune", "state": "MH", "timezone": "Asia/Kolkata",
       "open_time": "06:00", "close_time": "22:00", "checkin_grace_min": 30, "default_unload_min": 60}


def shipment_body(fid, **kw):
    return {"order_reference": f"ORD-{uuid.uuid4().hex[:6]}", "destination_facility_id": str(fid),
            "customer_name": "Acme", "origin_name": "Plant", "origin_city": "Delhi", "product_category": "Goods",
            "load_weight_kg": 8000, "required_dock_type": "ANY", "priority_code": "NORMAL",
            "expected_unload_min": 60, **kw}


def csv_file(text: str):
    return {"file": ("x.csv", io.BytesIO(text.encode()), "text/csv")}


# ---------------- facilities ----------------
async def test_facility_crud_and_audit(client, world):
    await login(client, "admin")
    r = await client.post("/api/v1/facilities", json=FAC)
    assert r.status_code == 201 and r.json()["code"] == "FAC-NEW" and r.json()["open_time"] == "06:00"
    fid = r.json()["id"]
    assert (await client.post("/api/v1/facilities", json=FAC)).status_code == 409
    p = await client.patch(f"/api/v1/facilities/{fid}", json={"city": "Mumbai", "active_flag": False})
    assert p.json()["city"] == "Mumbai" and p.json()["active_flag"] is False
    assert (await client.get("/api/v1/facilities", params={"active": "false"})).json()["total"] == 1
    audit = (await client.get("/api/v1/audit", params={"entity": "facilities", "action": "update"})).json()["items"]
    assert audit[0]["before"]["city"] == "Pune" and audit[0]["after"]["city"] == "Mumbai"


async def test_facility_validation(client, world):
    await login(client, "admin")
    assert (await client.post("/api/v1/facilities", json={**FAC, "close_time": "05:00"})).status_code == 422
    assert (await client.post("/api/v1/facilities", json={**FAC, "timezone": "Mars/Base"})).status_code == 422
    assert (await client.post("/api/v1/facilities", json={**FAC, "code": "bad code!"})).status_code == 422


async def test_facility_writes_forbidden_for_others(client, world):
    for who in ("facility_planner", "coordinator", "carrier_user"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post("/api/v1/facilities", json=FAC)).status_code == 403
    client.cookies.clear()
    await login(client, "facility_planner")
    assert (await client.patch(f"/api/v1/facilities/{world.facility_a.id}", json={"city": "X"})).status_code == 403


async def test_planner_cannot_open_other_facility(client, world):
    await login(client, "facility_planner")
    assert (await client.get(f"/api/v1/facilities/{world.facility_a.id}")).status_code == 200
    assert (await client.get(f"/api/v1/facilities/{world.facility_b.id}")).status_code == 404


async def test_contacts_and_missing_email_flag(client, world):
    await login(client, "admin")
    fid = world.facility_a.id
    c = await client.post(f"/api/v1/facilities/{fid}/contacts", json={"contact_role": "Gate", "contact_name": "Ravi"})
    assert c.status_code == 201 and c.json()["missing_email"] is True
    cid = c.json()["id"]
    u = await client.patch(f"/api/v1/facilities/{fid}/contacts/{cid}", json={"email": "ravi@dc.in"})
    assert u.json()["missing_email"] is False
    assert (await client.delete(f"/api/v1/facilities/{fid}/contacts/{cid}")).status_code == 204
    d = (await client.get(f"/api/v1/facilities/{fid}")).json()
    assert d["contacts"][0]["active_flag"] is False and d["dock_count"] == 0
    assert (await client.patch(f"/api/v1/facilities/{world.facility_b.id}/contacts/{cid}", json={})).status_code == 404


async def test_facility_csv_import_dry_run_then_commit(client, world):
    await login(client, "admin")
    good = "code,facility_name,city,state,open_time,close_time\nFAC-X1,X One,Agra,UP,06:00,20:00\nFAC-X2,X Two,Kota,RJ,07:00,21:00\n"
    dry = (await client.post("/api/v1/facilities/import?dry_run=true", files=csv_file(good))).json()
    assert dry == {"dry_run": True, "created": 2, "errors": []}
    assert (await client.get("/api/v1/facilities")).json()["total"] == 2  # nothing written yet
    real = (await client.post("/api/v1/facilities/import?dry_run=false", files=csv_file(good))).json()
    assert real["created"] == 2
    assert (await client.get("/api/v1/facilities")).json()["total"] == 4


async def test_facility_csv_import_rejects_bad_rows_atomically(client, world):
    await login(client, "admin")
    bad = ("code,facility_name,city,state,open_time,close_time\nFAC-OK,Ok,A,B,06:00,20:00\n"
           "FAC-A,Dup of A,A,B,06:00,20:00\nFAC-BAD,Bad,A,B,10:00,09:00\n")
    r = (await client.post("/api/v1/facilities/import?dry_run=false", files=csv_file(bad))).json()
    assert r["created"] == 0 and [e["row"] for e in r["errors"]] == [3, 4]
    assert (await client.get("/api/v1/facilities")).json()["total"] == 2
    assert (await client.post("/api/v1/facilities/import", files=csv_file("code,city\nX,Y\n"))).status_code == 422


async def test_facilities_export_and_search_sort(client, world):
    await login(client, "admin")
    assert [i["code"] for i in (await client.get("/api/v1/facilities", params={"sort": "-code"})).json()["items"]] == ["FAC-B", "FAC-A"]
    assert (await client.get("/api/v1/facilities", params={"q": "gurgaon"})).json()["total"] == 1
    assert (await client.get("/api/v1/facilities", params={"sort": "evil; drop"})).status_code == 422
    csv = await client.get("/api/v1/facilities/export.csv")
    assert csv.headers["content-type"].startswith("text/csv") and "FAC-A" in csv.text


# ---------------- carriers ----------------
async def test_carrier_crud_and_detail(client, world):
    from app.core.db import async_session_factory
    from app.modules.vehicles.models import VehicleType  # noqa: F401

    await login(client, "admin")
    r = await client.post("/api/v1/carriers", json={"code": "car-n", "carrier_name": "New Carrier",
                                                    "allowed_vehicle_type_codes": ["VT1"]})
    assert r.status_code == 201 and r.json()["code"] == "CAR-N"
    assert (await client.post("/api/v1/carriers", json={"code": "CAR-N2", "carrier_name": "X",
                                                        "allowed_vehicle_type_codes": ["NOPE"]})).status_code == 422
    assert (await client.post("/api/v1/carriers", json={"code": "CAR-N", "carrier_name": "Other"})).status_code == 409
    d = (await client.get(f"/api/v1/carriers/{world.carrier_a.id}")).json()
    assert (d["driver_count"], d["vehicle_count"], d["shipments_total"], d["shipments_active"]) == (1, 1, 1, 1)
    p = await client.patch(f"/api/v1/carriers/{r.json()['id']}", json={"active_flag": False})
    assert p.json()["active_flag"] is False
    assert async_session_factory is not None


async def test_carrier_user_cannot_write_or_see_other_carrier(client, world):
    await login(client, "carrier_user")
    assert (await client.post("/api/v1/carriers", json={"code": "CAR-Z", "carrier_name": "Z"})).status_code == 403
    assert (await client.get(f"/api/v1/carriers/{world.carrier_b.id}")).status_code == 404
    assert (await client.get(f"/api/v1/carriers/{world.carrier_a.id}")).status_code == 200


async def test_vehicle_types(client, world):
    await login(client, "admin")
    assert (await client.get("/api/v1/vehicle-types")).json() == [{"code": "VT1", "description": "Truck"}]


# ---------------- drivers directory ----------------
async def test_drivers_directory_filters(client, world):
    await login(client, "admin")
    all_ = (await client.get("/api/v1/drivers")).json()
    assert all_["total"] == 2 and all_["items"][0]["carrier_name"].startswith("Carrier")
    assert all_["items"][0]["active_shipments"] == 1 and all_["items"][0]["verified"] is False
    only_b = (await client.get("/api/v1/drivers", params={"carrier_id": str(world.carrier_b.id)})).json()
    assert [d["code"] for d in only_b["items"]] == ["DRV-B"]
    assert (await client.get("/api/v1/drivers", params={"verified": "true"})).json()["total"] == 0
    assert (await client.get("/api/v1/drivers", params={"q": "driver a"})).json()["total"] == 1
    assert "DRV-A" in (await client.get("/api/v1/drivers/export.csv")).text


# ---------------- shipments ----------------
async def test_shipment_create_codes_and_validation(client, world):
    await login(client, "admin")
    fid = world.facility_a.id
    a = await client.post("/api/v1/shipments", json=shipment_body(fid, requested_date="2026-12-01"))
    b = await client.post("/api/v1/shipments", json=shipment_body(fid))
    assert a.status_code == 201 and a.json()["code"] == "SHP1001" and b.json()["code"] == "SHP1002"
    assert a.json()["current_status"] == "PLANNED" and a.json()["offer_status"] == "draft"
    assert a.json()["original_eta_ts"].startswith("2026-12-01T00:30")  # facility opens 06:00 IST
    assert (await client.post("/api/v1/shipments", json=shipment_body(fid, required_dock_type="STANDARD",
                                                                      temperature_control_required=True))).status_code == 422
    assert (await client.post("/api/v1/shipments", json=shipment_body(fid, load_weight_kg=0))).status_code == 422
    assert (await client.post("/api/v1/shipments", json=shipment_body(fid, priority_code="URGENT"))).status_code == 422
    assert (await client.post("/api/v1/shipments", json=shipment_body(uuid.uuid4()))).status_code == 422
    dup = shipment_body(fid, order_reference="ORD-A")
    assert (await client.post("/api/v1/shipments", json=dup)).status_code == 409


async def test_shipment_write_permissions(client, world):
    for who in ("facility_planner", "coordinator", "carrier_user"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id))).status_code == 403
        assert (await client.post(f"/api/v1/shipments/{world.shipment_a.id}/cancel", json={"reason": "no"})).status_code == 403


async def test_offer_flow_and_carrier_visibility(client, world):
    await login(client, "admin")
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id))).json()
    sid = s["id"]
    client.cookies.clear()
    await login(client, "carrier_user")
    assert sid not in [i["id"] for i in (await client.get("/api/v1/shipments")).json()["items"]]  # draft hidden
    assert (await client.get(f"/api/v1/shipments/{sid}")).status_code == 404
    client.cookies.clear()
    await login(client, "admin")
    o = await client.post(f"/api/v1/shipments/{sid}/offer", json={"carrier_id": str(world.carrier_a.id)})
    assert o.status_code == 200 and o.json()["offer_status"] == "offered" and o.json()["carrier_name"] == "Carrier A"
    client.cookies.clear()
    await login(client, "carrier_user")
    assert (await client.get(f"/api/v1/shipments/{sid}")).status_code == 200
    client.cookies.clear()
    await login(client, "carrier_b")
    assert (await client.get(f"/api/v1/shipments/{sid}")).status_code == 404


async def test_offer_rejects_inactive_carrier_and_assigned_shipment(client, world):
    await login(client, "admin")
    await client.patch(f"/api/v1/carriers/{world.carrier_b.id}", json={"active_flag": False})
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id))).json()
    assert (await client.post(f"/api/v1/shipments/{s['id']}/offer", json={"carrier_id": str(world.carrier_b.id)})).status_code == 422
    assert (await client.post(f"/api/v1/shipments/{world.shipment_a.id}/offer",
                              json={"carrier_id": str(world.carrier_a.id)})).status_code == 409


async def test_edit_and_cancel_rules(client, world):
    await login(client, "admin")
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id))).json()
    e = await client.patch(f"/api/v1/shipments/{s['id']}", json={"priority_code": "CRITICAL", "load_weight_kg": 9000})
    assert e.json()["priority_code"] == "CRITICAL"
    bad = await client.patch(f"/api/v1/shipments/{s['id']}", json={"required_dock_type": "HEAVY",
                                                                   "temperature_control_required": True})
    assert bad.status_code == 422
    c = await client.post(f"/api/v1/shipments/{s['id']}/cancel", json={"reason": "customer cancelled"})
    assert c.json()["current_status"] == "CANCELLED"
    assert (await client.post(f"/api/v1/shipments/{s['id']}/cancel", json={"reason": "again"})).status_code == 409
    assert (await client.patch(f"/api/v1/shipments/{s['id']}", json={"priority_code": "LOW"})).status_code == 409


async def test_cancel_blocked_while_appointment_active(client, world):
    from datetime import UTC, datetime, time, timedelta

    from app.core.db import async_session_factory
    from app.modules.appointments.models import Appointment
    from app.modules.docks.models import Dock
    from app.modules.slots.models import AppointmentSlot

    now = datetime.now(UTC)
    async with async_session_factory() as db:
        dock = Dock(code="D1", facility_id=world.facility_a.id, dock_code="D1", dock_type="STANDARD",
                    max_vehicle_weight_kg=20000)
        db.add(dock)
        await db.flush()
        slot = AppointmentSlot(code="S1", facility_id=world.facility_a.id, dock_id=dock.id,
                               slot_start_ts=now, slot_end_ts=now + timedelta(hours=1))
        db.add(slot)
        await db.flush()
        db.add(Appointment(code="APT1", shipment_id=world.shipment_a.id, slot_id=slot.id,
                           appointment_status="CONFIRMED", booking_source="PLANNER", booked_at=now))
        await db.commit()
    assert time(0) is not None
    await login(client, "admin")
    r = await client.post(f"/api/v1/shipments/{world.shipment_a.id}/cancel", json={"reason": "customer cancelled"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTIVE_APPOINTMENT"
    tl = (await client.get(f"/api/v1/shipments/{world.shipment_a.id}/timeline")).json()
    assert any(e["kind"] == "appointment" and "S1" in e["detail"] for e in tl["events"])


async def test_timeline_collects_history(client, world):
    await login(client, "admin")
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id))).json()
    await client.patch(f"/api/v1/shipments/{s['id']}", json={"priority_code": "HIGH"})
    await client.post(f"/api/v1/shipments/{s['id']}/offer", json={"carrier_id": str(world.carrier_a.id)})
    await client.post(f"/api/v1/shipments/{s['id']}/cancel", json={"reason": "plans changed"})
    tl = (await client.get(f"/api/v1/shipments/{s['id']}/timeline")).json()
    kinds = [e["kind"] for e in tl["events"]]
    assert kinds[0] == "created" and "offered" in kinds and kinds[-1] == "cancelled"
    assert tl["threads"] == [] and all(e["actor"] for e in tl["events"][1:])
    assert tl["events"] == sorted(tl["events"], key=lambda e: e["ts"])


async def test_shipment_import(client, world):
    await login(client, "admin")
    head = ("order_reference,destination_facility_code,customer_name,origin_name,origin_city,product_category,"
            "load_weight_kg,pallet_count,required_dock_type,temperature_control_required,priority_code,"
            "expected_unload_min,requested_date\n")
    good = head + "IMP-1,FAC-A,Cust,Plant,Delhi,Food,5000,10,REEFER,true,HIGH,45,2026-12-02\nIMP-2,FAC-B,Cust,Plant,Delhi,Tools,7000,,,,,60,\n"
    dry = (await client.post("/api/v1/shipments/import?dry_run=true", files=csv_file(good))).json()
    assert dry["created"] == 2 and dry["errors"] == []
    assert (await client.get("/api/v1/shipments")).json()["total"] == 2
    ok = (await client.post("/api/v1/shipments/import?dry_run=false", files=csv_file(good))).json()
    assert ok["created"] == 2
    items = (await client.get("/api/v1/shipments", params={"q": "IMP-"})).json()["items"]
    assert sorted(i["code"] for i in items) == ["SHP1001", "SHP1002"]
    bad = head + "IMP-3,NOPE,Cust,Plant,Delhi,Food,5000,,,,,45,\nIMP-1,FAC-A,Cust,Plant,Delhi,Food,5000,,,,,45,\nIMP-4,FAC-A,C,P,D,F,abc,,,,,45,\n"
    r = (await client.post("/api/v1/shipments/import?dry_run=false", files=csv_file(bad))).json()
    assert r["created"] == 0 and [e["row"] for e in r["errors"]] == [2, 3, 4]
    assert (await client.get("/api/v1/shipments")).json()["total"] == 4


async def test_shipment_filters_and_csv_injection_guard(client, world):
    await login(client, "admin")
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_b.id, customer_name="=HYPERLINK(1)"))).json()
    assert (await client.get("/api/v1/shipments", params={"facility_id": str(world.facility_b.id)})).json()["total"] == 2
    assert (await client.get("/api/v1/shipments", params={"offer_status": "draft"})).json()["total"] == 1
    assert (await client.get("/api/v1/shipments", params={"sort": "-priority_code"})).status_code == 200
    csv = (await client.get("/api/v1/shipments/export.csv")).text
    assert "'=HYPERLINK(1)" in csv and s["code"] in csv


# ---------------- idempotency ----------------
async def test_idempotency_key_replays_response(client, world):
    await login(client, "admin")
    h = {"Idempotency-Key": "abc-123"}
    body = shipment_body(world.facility_a.id)
    r1 = await client.post("/api/v1/shipments", json=body, headers=h)
    r2 = await client.post("/api/v1/shipments", json=body, headers=h)
    assert r1.status_code == 201 and r2.status_code == 201 and r1.json() == r2.json()
    assert r2.headers.get("idempotent-replay") == "true"
    assert (await client.get("/api/v1/shipments", params={"q": body["order_reference"]})).json()["total"] == 1
    r3 = await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id), headers={"Idempotency-Key": "other"})
    assert r3.status_code == 201 and r3.json()["id"] != r1.json()["id"]
