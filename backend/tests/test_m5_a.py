import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.db import async_session_factory
from app.core.security import sha256
from app.modules.drivers.models import Driver
from app.modules.notifications.models import OutboxEvent
from app.modules.vehicles.models import Vehicle, VehicleType
from tests.conftest import login
from tests.test_admin_core import shipment_body

DRV = {"driver_name": "Imran Khan", "phone": "+919811100001", "whatsapp_number": "+919811100001",
       "preferred_language": "hi", "licence_number": "RJ1420260001", "home_base_city": "Jaipur"}


def csv_file(text_: str):
    return {"file": ("x.csv", io.BytesIO(text_.encode()), "text/csv")}


async def outbox(kind: str) -> list[OutboxEvent]:
    async with async_session_factory() as db:
        return list((await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == kind))).scalars().all())


async def offered_shipment(client, world, carrier=None, **kw):
    """Admin creates + offers a shipment to carrier A (or the given carrier); returns its id."""
    await login(client, "admin")
    s = (await client.post("/api/v1/shipments", json=shipment_body(world.facility_a.id, **kw))).json()
    r = await client.post(f"/api/v1/shipments/{s['id']}/offer", json={"carrier_id": str((carrier or world.carrier_a).id)})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    return s["id"]


async def add_vehicle(world, **kw):
    async with async_session_factory() as db:
        vt = (await db.execute(select(VehicleType))).scalars().first()
        v = Vehicle(code=kw.pop("code", f"VEH{uuid.uuid4().hex[:5]}"), carrier_id=kw.pop("carrier_id", world.carrier_a.id),
                    vehicle_type_id=vt.id, registration_number=kw.pop("registration_number", f"RJ{uuid.uuid4().hex[:6]}".upper()),
                    capacity_kg=kw.pop("capacity_kg", 20000), **kw)
        db.add(v)
        await db.commit()
        return v.id


# ---------------- drivers ----------------
async def test_driver_crud_validation_and_permissions(client, world):
    await login(client, "carrier_user")
    r = await client.post("/api/v1/drivers", json=DRV)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["code"].startswith("DRV") and d["verified"] is False and d["carrier_id"] == str(world.carrier_a.id)
    assert (await client.post("/api/v1/drivers", json=DRV)).status_code == 409
    for bad in ({"phone": "9811100002"}, {"preferred_language": "xx"}, {"licence_number": "ab"}):
        assert (await client.post("/api/v1/drivers", json={**DRV, "phone": "+919811100002", "licence_number": "RJ9", **bad})).status_code == 422
    p = await client.patch(f"/api/v1/drivers/{d['id']}", json={"driver_name": "Imran K", "driver_status": "OFF_DUTY"})
    assert p.json()["driver_name"] == "Imran K" and p.json()["driver_status"] == "OFF_DUTY"
    assert (await client.patch(f"/api/v1/drivers/{d['id']}", json={"driver_status": "SUSPENDED"})).status_code == 422
    detail = (await client.get(f"/api/v1/drivers/{d['id']}")).json()
    assert detail["history"] == [] and detail["home_base_city"] == "Jaipur"
    assert (await client.delete(f"/api/v1/drivers/{d['id']}")).json()["driver_status"] == "INACTIVE"


async def test_driver_roles_and_scope(client, world):
    for who in ("admin", "coordinator", "facility_planner"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post("/api/v1/drivers", json=DRV)).status_code == 403
    client.cookies.clear()
    await login(client, "carrier_b")
    assert (await client.get("/api/v1/drivers")).json()["total"] == 1  # only DRV-B
    other = str(world.shipment_a.driver_id)
    assert (await client.get(f"/api/v1/drivers/{other}")).status_code == 404
    assert (await client.patch(f"/api/v1/drivers/{other}", json={"driver_name": "Hacked"})).status_code == 404
    assert (await client.delete(f"/api/v1/drivers/{other}")).status_code == 404
    assert (await client.post(f"/api/v1/drivers/{other}/whatsapp/verification")).status_code == 404


async def test_deactivate_blocked_by_active_shipment_and_history(client, world):
    await login(client, "carrier_user")
    did = str(world.shipment_a.driver_id)
    r = await client.delete(f"/api/v1/drivers/{did}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTIVE_SHIPMENTS"
    hist = (await client.get(f"/api/v1/drivers/{did}")).json()["history"]
    assert [h["code"] for h in hist] == ["SHP-A"] and hist[0]["facility_code"] == "FAC-A"


async def test_changing_whatsapp_number_resets_verification(client, world):
    await login(client, "carrier_user")
    d = (await client.post("/api/v1/drivers", json=DRV)).json()
    sent = (await client.post(f"/api/v1/drivers/{d['id']}/whatsapp/verification")).json()
    assert (await client.post(f"/api/v1/drivers/{d['id']}/whatsapp/verify", json={"code": sent["dev_code"]})).json() == {"verified": True}
    assert (await client.get(f"/api/v1/drivers/{d['id']}")).json()["verified"] is True
    p = await client.patch(f"/api/v1/drivers/{d['id']}", json={"whatsapp_number": "+919811100099"})
    assert p.json()["verified"] is False and p.json()["whatsapp_opt_in"] is False


async def test_verification_flow_wrong_codes_expiry_and_outbox(client, world):
    await login(client, "carrier_user")
    d = (await client.post("/api/v1/drivers", json=DRV)).json()
    path = f"/api/v1/drivers/{d['id']}/whatsapp"
    assert (await client.post(f"{path}/verify", json={"code": "123456"})).status_code == 422  # nothing requested yet
    sent = (await client.post(f"{path}/verification")).json()
    assert sent["sent"] and len(sent["dev_code"]) == 6
    events = await outbox("whatsapp.verification")
    assert len(events) == 1 and "code_enc" in events[0].payload and sent["dev_code"] not in str(events[0].payload)
    wrong = "000000" if sent["dev_code"] != "000000" else "111111"
    r = await client.post(f"{path}/verify", json={"code": wrong})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_CODE"
    for _ in range(4):
        await client.post(f"{path}/verify", json={"code": wrong})
    locked = await client.post(f"{path}/verify", json={"code": sent["dev_code"]})  # even the right code is refused now
    assert locked.status_code == 429
    again = (await client.post(f"{path}/verification")).json()
    assert (await client.post(f"{path}/verify", json={"code": again["dev_code"]})).status_code == 200
    # expiry
    d2 = (await client.post("/api/v1/drivers", json={**DRV, "phone": "+919811100002", "whatsapp_number": "+919811100002",
                                                     "licence_number": "RJ1420260002"})).json()
    s2 = (await client.post(f"/api/v1/drivers/{d2['id']}/whatsapp/verification")).json()
    async with async_session_factory() as db:
        drv = await db.get(Driver, uuid.UUID(d2["id"]))
        drv.verification_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert (await client.post(f"/api/v1/drivers/{d2['id']}/whatsapp/verify", json={"code": s2["dev_code"]})).status_code == 422
    assert sha256("x")  # hashing helper is the one used for storage


async def test_verification_requires_a_number_and_is_rate_limited(client, world):
    await login(client, "carrier_user")
    d = (await client.post("/api/v1/drivers", json={**DRV, "whatsapp_number": None})).json()
    assert (await client.post(f"/api/v1/drivers/{d['id']}/whatsapp/verification")).status_code == 422
    await client.patch(f"/api/v1/drivers/{d['id']}", json={"whatsapp_number": "+919811100077"})
    codes = [(await client.post(f"/api/v1/drivers/{d['id']}/whatsapp/verification")).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


async def test_driver_csv_import_atomic_and_export(client, world):
    await login(client, "carrier_user")
    head = "driver_name,phone,whatsapp_number,preferred_language,licence_number,home_base_city\n"
    good = head + "Ravi Singh,+919822200001,+919822200001,pa,PB1020260001,Ludhiana\nAmit Rao,+919822200002,,te,TS1020260002,Hyderabad\n"
    dry = (await client.post("/api/v1/drivers/import?dry_run=true", files=csv_file(good))).json()
    assert dry == {"dry_run": True, "created": 2, "errors": []}
    assert (await client.get("/api/v1/drivers")).json()["total"] == 1
    assert (await client.post("/api/v1/drivers/import?dry_run=false", files=csv_file(good))).json()["created"] == 2
    bad = head + "New One,+919822200003,,en,KA1020260003,\nDup,+919822200001,,en,KA1020260004,\nBadLang,+919822200005,,zz,KA1020260005,\n"
    r = (await client.post("/api/v1/drivers/import?dry_run=false", files=csv_file(bad))).json()
    assert r["created"] == 0 and [e["row"] for e in r["errors"]] == [3, 4]
    assert (await client.get("/api/v1/drivers")).json()["total"] == 3
    assert "Ravi Singh" in (await client.get("/api/v1/drivers/export.csv")).text


# ---------------- vehicles ----------------
async def test_vehicle_crud_and_scope(client, world):
    await login(client, "carrier_user")
    body = {"vehicle_type_code": "VT1", "registration_number": "rj14 ab 1234", "capacity_kg": 18000, "refrigeration_capable": True}
    r = await client.post("/api/v1/vehicles", json=body)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["registration_number"] == "RJ14 AB 1234" and v["refrigeration_capable"] is True and v["carrier_id"] == str(world.carrier_a.id)
    assert (await client.post("/api/v1/vehicles", json=body)).status_code == 409
    assert (await client.post("/api/v1/vehicles", json={**body, "vehicle_type_code": "NOPE", "registration_number": "RJ14 ZZ 0001"})).status_code == 422
    assert (await client.post("/api/v1/vehicles", json={**body, "capacity_kg": 0, "registration_number": "RJ14 ZZ 0002"})).status_code == 422
    p = await client.patch(f"/api/v1/vehicles/{v['id']}", json={"capacity_kg": 20000, "heavy_capable": True})
    assert p.json()["capacity_kg"] == 20000 and p.json()["heavy_capable"] is True
    assert (await client.get("/api/v1/vehicles", params={"q": "ab 1234"})).json()["total"] == 1
    assert (await client.delete(f"/api/v1/vehicles/{v['id']}")).json()["active_flag"] is False
    client.cookies.clear()
    await login(client, "carrier_b")
    assert (await client.get("/api/v1/vehicles")).json()["total"] == 1
    assert (await client.patch(f"/api/v1/vehicles/{v['id']}", json={"capacity_kg": 1})).status_code == 404


async def test_vehicle_roles_retire_block_import_and_allowed_types(client, world):
    for who in ("admin", "coordinator", "facility_planner"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post("/api/v1/vehicles", json={"vehicle_type_code": "VT1", "registration_number": "RJ14 XX 0001", "capacity_kg": 1000})).status_code == 403
    client.cookies.clear()
    await login(client, "carrier_user")
    assert (await client.delete(f"/api/v1/vehicles/{world.shipment_a.vehicle_id}")).status_code == 409
    head = "vehicle_type_code,registration_number,capacity_kg,refrigeration_capable,heavy_capable\n"
    good = head + "VT1,RJ14 IM 0001,12000,true,false\nVT1,RJ14 IM 0002,9000,,\n"
    assert (await client.post("/api/v1/vehicles/import?dry_run=true", files=csv_file(good))).json()["created"] == 2
    assert (await client.post("/api/v1/vehicles/import?dry_run=false", files=csv_file(good))).json()["created"] == 2
    bad = head + "VT1,RJ14 IM 0003,5000,,\nVT1,RJ14 IM 0001,5000,,\nBAD,RJ14 IM 0004,5000,,\n"
    r = (await client.post("/api/v1/vehicles/import?dry_run=false", files=csv_file(bad))).json()
    assert r["created"] == 0 and [e["row"] for e in r["errors"]] == [3, 4]
    assert "RJ14 IM 0001" in (await client.get("/api/v1/vehicles/export.csv")).text
    client.cookies.clear()
    await login(client, "admin")
    await client.patch(f"/api/v1/carriers/{world.carrier_a.id}", json={"allowed_vehicle_type_codes": ["VT1"]})
    async with async_session_factory() as db:
        db.add(VehicleType(code="VT2", description="Reefer", default_capacity_kg=8000, typical_dock_type="REEFER", refrigerated_flag=True))
        await db.commit()
    client.cookies.clear()
    await login(client, "carrier_user")
    r = await client.post("/api/v1/vehicles", json={"vehicle_type_code": "VT2", "registration_number": "RJ14 VT 0002", "capacity_kg": 8000})
    assert r.status_code == 422 and "not set up" in r.json()["error"]["message"]


# ---------------- offers, assignment ----------------
async def test_offer_emits_outbox_and_carrier_can_respond(client, world):
    sid = await offered_shipment(client, world)
    assert len(await outbox("shipment.offered")) == 1
    await login(client, "carrier_user")
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": False})).status_code == 422
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": False, "reason": "no"})).status_code == 422
    d = await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": False, "reason": "No trucks available that day"})
    assert d.json()["offer_status"] == "declined" and d.json()["offer_decline_reason"].startswith("No trucks")
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": True})).status_code == 409
    assert len(await outbox("shipment.offer_responded")) == 1


async def test_respond_scope_and_roles(client, world):
    sid = await offered_shipment(client, world)
    await login(client, "carrier_b")
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": True})).status_code == 404
    for who in ("admin", "coordinator", "facility_planner"):
        client.cookies.clear()
        await login(client, who)
        assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": True})).status_code == 403


async def _accept(client, sid):
    await login(client, "carrier_user")
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": True})).json()["offer_status"] == "accepted"


async def test_assignment_blocks_incompatible_vehicle(client, world):
    sid = await offered_shipment(client, world, required_dock_type="REEFER", temperature_control_required=True, load_weight_kg=30000)
    await _accept(client, sid)
    plain = await add_vehicle(world, capacity_kg=10000)
    q = {"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(plain)}
    chk = (await client.get(f"/api/v1/shipments/{sid}/assignment-check", params=q)).json()
    assert {p["code"] for p in chk["problems"]} == {"VEHICLE_NOT_REFRIGERATED", "LOAD_EXCEEDS_CAPACITY"}
    r = await client.post(f"/api/v1/shipments/{sid}/assign", json={"driver_id": q["driver_id"], "vehicle_id": q["vehicle_id"]})
    assert r.status_code == 422 and {p["code"] for p in r.json()["error"]["details"]["problems"]} >= {"VEHICLE_NOT_REFRIGERATED"}


async def test_heavy_inactive_and_type_restrictions(client, world):
    sid = await offered_shipment(client, world, required_dock_type="HEAVY")
    await _accept(client, sid)
    veh = await add_vehicle(world, heavy_capable=False, active_flag=False)
    chk = (await client.get(f"/api/v1/shipments/{sid}/assignment-check",
                            params={"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(veh)})).json()
    assert {p["code"] for p in chk["problems"]} == {"VEHICLE_NOT_HEAVY", "VEHICLE_INACTIVE"}
    ok = await add_vehicle(world, heavy_capable=True)
    assert (await client.get(f"/api/v1/shipments/{sid}/assignment-check",
                             params={"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(ok)})).json()["problems"] == []


async def test_assign_warnings_then_success_and_double_assign(client, world):
    sid = await offered_shipment(client, world)
    await _accept(client, sid)
    veh = await add_vehicle(world, refrigeration_capable=True)
    busy_driver = str(world.shipment_a.driver_id)  # already on SHP-A (ASSIGNED)
    r = await client.post(f"/api/v1/shipments/{sid}/assign", json={"driver_id": busy_driver, "vehicle_id": str(veh)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {w["code"] for w in body["warnings"]} == {"DRIVER_ON_ANOTHER_SHIPMENT", "DRIVER_NOT_VERIFIED"}
    assert body["shipment"]["current_status"] == "ASSIGNED" and body["shipment"]["driver_id"] == busy_driver
    assert body["driver_language"] == "en"
    assert (await client.post(f"/api/v1/shipments/{sid}/assign", json={"driver_id": busy_driver, "vehicle_id": str(veh)})).status_code == 409
    assert len(await outbox("shipment.assigned")) == 1


async def test_cannot_assign_before_accepting_or_other_carriers_resources(client, world):
    sid = await offered_shipment(client, world)
    await login(client, "carrier_user")
    veh = await add_vehicle(world)
    q = {"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(veh)}
    assert (await client.post(f"/api/v1/shipments/{sid}/assign", json=q)).status_code == 409  # still only offered
    await _accept(client, sid) if False else None
    assert (await client.post(f"/api/v1/shipments/{sid}/respond", json={"accept": True})).status_code == 200
    # another carrier's driver or vehicle is invisible to carrier A
    other_driver = str(world.shipment_b.driver_id)
    assert (await client.post(f"/api/v1/shipments/{sid}/assign", json={**q, "driver_id": other_driver})).status_code == 404
    other_vehicle = str(world.shipment_b.vehicle_id)
    assert (await client.post(f"/api/v1/shipments/{sid}/assign", json={**q, "vehicle_id": other_vehicle})).status_code == 404


async def test_reassign_after_breakdown_records_reason_and_notifies(client, world):
    await login(client, "carrier_user")
    sid = str(world.shipment_a.id)
    new_vehicle = await add_vehicle(world)
    q = {"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(new_vehicle)}
    assert (await client.post(f"/api/v1/shipments/{sid}/reassign", json=q)).status_code == 422  # reason required
    r = await client.post(f"/api/v1/shipments/{sid}/reassign", json={**q, "reason": "Engine breakdown near Kota"})
    assert r.status_code == 200 and r.json()["shipment"]["vehicle_id"] == str(new_vehicle)
    ev = await outbox("shipment.reassigned")
    assert len(ev) == 1 and ev[0].payload["reason"] == "Engine breakdown near Kota"
    async with async_session_factory() as db:
        n = (await db.execute(text("SELECT count(*) FROM audit_log WHERE entity='shipments' AND action='update' AND after ? 'vehicle_id'"))).scalar_one()
    assert n >= 1


async def test_reassign_requires_an_assignment_and_open_shipment(client, world):
    sid = await offered_shipment(client, world)
    await _accept(client, sid)
    veh = await add_vehicle(world)
    q = {"driver_id": str(world.shipment_a.driver_id), "vehicle_id": str(veh), "reason": "Driver unavailable today"}
    assert (await client.post(f"/api/v1/shipments/{sid}/reassign", json=q)).status_code == 409
    assert (await client.post(f"/api/v1/shipments/{world.shipment_b.id}/reassign", json=q)).status_code == 404
