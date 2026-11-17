"""Milestone 5 part B: notifications + outbox projection, carrier dashboard/tracker/slot-changes, carrier reports."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import async_session_factory
from app.main import app
from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.docks.models import Dock
from app.modules.drivers.models import Driver
from app.modules.eta.models import EtaUpdate
from app.modules.notifications import service as notif
from app.modules.notifications.models import Notification, OutboxEvent
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.users.models import User, UserScope
from tests.conftest import _HASH, PASSWORD, login

NOW = datetime.now(UTC).replace(microsecond=0)


# ---------------------------------------------------------------- helpers
async def slot(world, code, start, minutes=60, dock_code="D1"):
    async with async_session_factory() as db:
        dock = (await db.execute(select(Dock).where(Dock.facility_id == world.facility_a.id, Dock.dock_code == dock_code))).scalar_one_or_none()
        if dock is None:
            dock = Dock(code=f"FAC-A-{dock_code}", facility_id=world.facility_a.id, dock_code=dock_code, dock_type="STANDARD",
                        max_vehicle_weight_kg=30000)
            db.add(dock)
            await db.flush()
        s = AppointmentSlot(code=code, facility_id=world.facility_a.id, dock_id=dock.id, slot_start_ts=start,
                            slot_end_ts=start + timedelta(minutes=minutes))
        db.add(s)
        await db.commit()
        return s.id


async def appointment(world, slot_id, status="CONFIRMED", shipment=None, code=None, **kw):
    async with async_session_factory() as db:
        a = Appointment(code=code or f"APT-{uuid.uuid4().hex[:6]}", shipment_id=(shipment or world.shipment_a).id, slot_id=slot_id,
                        appointment_status=status, booking_source="PLANNER", booked_at=kw.pop("booked_at", NOW),
                        confirmed_at=kw.pop("confirmed_at", NOW if status == "CONFIRMED" else None), **kw)
        db.add(a)
        await db.commit()
        return a.id


async def shipment(world, code, *, carrier=None, driver=None, status="ASSIGNED", offer="accepted", facility=None, **kw):
    async with async_session_factory() as db:
        base = (await db.execute(select(Shipment).where(Shipment.code == "SHP-A"))).scalar_one()
        s = Shipment(code=code, order_reference=f"ORD-{code}", carrier_id=carrier.id if carrier else None,
                     driver_id=driver, vehicle_id=base.vehicle_id if driver else None, origin_name="O", origin_city="Delhi",
                     destination_facility_id=(facility or world.facility_a).id, customer_name="C", product_category="Goods",
                     load_weight_kg=5000, planned_departure_ts=NOW, original_eta_ts=kw.pop("eta", NOW), expected_unload_min=60,
                     current_status=status, offer_status=offer, **kw)
        db.add(s)
        await db.commit()
        return s.id


async def driver_id(code):
    async with async_session_factory() as db:
        return (await db.execute(select(Driver.id).where(Driver.code == code))).scalar_one()


async def add_user(world, email, role, *, carrier=None, facility=None):
    async with async_session_factory() as db:
        u = User(email=email, full_name=email, role=role, status="active", password_hash=_HASH)
        db.add(u)
        await db.flush()
        if carrier:
            db.add(UserScope(user_id=u.id, carrier_id=carrier.id))
        if facility:
            db.add(UserScope(user_id=u.id, facility_id=facility.id))
        await db.commit()


async def second_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def login_as(client, email):
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


async def add_note(**kw):
    async with async_session_factory() as db:
        n = Notification(type=kw.pop("type", "test"), title=kw.pop("title", "t"), **kw)
        db.add(n)
        await db.commit()
        return n.id


async def emit(event_type, payload, status="pending", **kw):
    async with async_session_factory() as db:
        db.add(OutboxEvent(event_type=event_type, payload=payload, status=status, **kw))
        await db.commit()


async def project(**kw):
    async with async_session_factory() as db:
        res = await notif.process_outbox(db, **kw)
        await db.commit()
        return res


async def notes():
    async with async_session_factory() as db:
        return (await db.execute(select(Notification).order_by(Notification.created_at, Notification.title))).scalars().all()


# ---------------------------------------------------------------- notifications: visibility, scope, read state
async def test_notification_visibility_by_role_and_scope(client, world):
    await add_user(world, "planner_b@test.io", "facility_planner", facility=world.facility_b)
    await add_note(title="carrier A", recipient_role="carrier_user", carrier_id=world.carrier_a.id)
    await add_note(title="carrier B", recipient_role="carrier_user", carrier_id=world.carrier_b.id)
    await add_note(title="all carriers", recipient_role="carrier_user")
    await add_note(title="coord", recipient_role="coordinator")
    await add_note(title="planner fac A", recipient_role="facility_planner", facility_id=world.facility_a.id)
    await add_note(title="planner fac B", recipient_role="facility_planner", facility_id=world.facility_b.id)
    async with async_session_factory() as db:
        admin = (await db.execute(select(User).where(User.email == "admin@test.io"))).scalar_one()
    await add_note(title="admin only", recipient_user_id=admin.id)

    async def titles(who):
        client.cookies.clear()
        await login(client, who)
        return sorted(i["title"] for i in (await client.get("/api/v1/notifications")).json()["items"])

    assert await titles("carrier_user") == ["all carriers", "carrier A"]
    assert await titles("carrier_b") == ["all carriers", "carrier B"]
    assert await titles("coordinator") == ["coord"]
    assert await titles("facility_planner") == ["planner fac A"]
    assert await titles("admin") == ["admin only"]
    client.cookies.clear()
    await login_as(client, "planner_b@test.io")
    assert [i["title"] for i in (await client.get("/api/v1/notifications")).json()["items"]] == ["planner fac B"]


async def test_notifications_require_login(client, world):
    assert (await client.get("/api/v1/notifications")).status_code == 401


async def test_read_state_is_per_user_and_scoped(client, world):
    await add_user(world, "carrier_a2@test.io", "carrier_user", carrier=world.carrier_a)
    n1 = await add_note(title="first", recipient_role="carrier_user", carrier_id=world.carrier_a.id)
    await add_note(title="second", recipient_role="carrier_user", carrier_id=world.carrier_a.id)
    other = await add_note(title="B's", recipient_role="carrier_user", carrier_id=world.carrier_b.id)
    await login(client, "carrier_user")
    page = (await client.get("/api/v1/notifications")).json()
    assert page["total"] == 2 and page["unread"] == 2 and not any(i["read"] for i in page["items"])
    assert (await client.post(f"/api/v1/notifications/{n1}/read")).status_code == 204
    assert (await client.post(f"/api/v1/notifications/{n1}/read")).status_code == 204  # idempotent
    page = (await client.get("/api/v1/notifications")).json()
    assert page["unread"] == 1 and {i["title"]: i["read"] for i in page["items"]} == {"first": True, "second": False}
    assert [i["title"] for i in (await client.get("/api/v1/notifications", params={"unread_only": "true"})).json()["items"]] == ["second"]
    assert (await client.post(f"/api/v1/notifications/{other}/read")).status_code == 404  # another carrier's row
    async with await second_client() as c2:  # a colleague at the same carrier is unaffected
        await login_as(c2, "carrier_a2@test.io")
        assert (await c2.get("/api/v1/notifications")).json()["unread"] == 2
    assert (await client.post("/api/v1/notifications/read-all")).json() == {"marked": 1}
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 0


async def test_notification_paging_and_csrf(client, world):
    for i in range(5):
        await add_note(title=f"n{i}", recipient_role="carrier_user", carrier_id=world.carrier_a.id)
    await login(client, "carrier_user")
    page = (await client.get("/api/v1/notifications", params={"limit": 2, "offset": 2})).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    del client.headers["X-CSRF-Token"]
    assert (await client.post("/api/v1/notifications/read-all")).status_code == 403


# ---------------------------------------------------------------- outbox projection
FULL = {"carrier": ("carrier_user", True), "planner": ("facility_planner", False), "coord": ("coordinator", False)}
EXPECTED = {
    "shipment.offered": {"carrier"}, "appointment.confirmed": {"carrier"}, "appointment.pending_confirmation": {"carrier", "planner"},
    "appointment.rejected": {"carrier"}, "appointment.cancelled": {"carrier"}, "appointment.no_show": {"carrier"},
    "request.suggested": {"carrier"}, "request.held": {"carrier"}, "request.rejected": {"carrier"}, "hold.placed": {"carrier"},
    "hold.expired": {"carrier"}, "pending.expired": {"carrier"}, "escalation.created": {"carrier", "coord"},
    "replan.requested": {"carrier", "planner"}, "eta.stale": {"carrier", "coord"}, "shipment.reassigned": {"coord"},
    "shipment.offer_responded": {"coord"}, "shipment.assigned": {"coord"},
}


@pytest.mark.parametrize("event_type", sorted(EXPECTED))
async def test_outbox_audiences_per_event_type(client, world, event_type):
    await emit(event_type, {"shipment_id": str(world.shipment_a.id), "reason": "because"})
    res = await project()
    got = await notes()
    roles = {n.recipient_role for n in got}
    assert roles == {FULL[k][0] for k in EXPECTED[event_type]}
    assert res.sent == 1 and res.failed == 0 and res.notifications == len(got)
    for n in got:
        assert n.type == event_type and "SHP-A" in n.title and n.payload["shipment_code"] == "SHP-A"
        if n.recipient_role == "carrier_user":
            assert n.carrier_id == world.carrier_a.id and n.facility_id is None
        if n.recipient_role == "facility_planner":
            assert n.facility_id == world.facility_a.id
    async with async_session_factory() as db:
        assert (await db.execute(select(OutboxEvent))).scalar_one().status == "sent"


async def test_outbox_unknown_type_and_missing_shipment_are_marked_sent(client, world):
    await emit("something.else", {"shipment_id": str(world.shipment_a.id)})
    await emit("hold.placed", {})
    await emit("hold.placed", {"shipment_id": str(uuid.uuid4())})
    res = await project()
    assert res.sent == 3 and res.notifications == 0 and await notes() == []


async def test_outbox_is_idempotent(client, world):
    await emit("appointment.confirmed", {"shipment_id": str(world.shipment_a.id)})
    assert (await project()).sent == 1
    again = await project()
    assert again.sent == 0 and again.notifications == 0 and len(await notes()) == 1


async def test_outbox_title_contains_slot_times(client, world):
    sid = await slot(world, "SLOT-T1", NOW + timedelta(hours=2))
    aid = await appointment(world, sid)
    await emit("appointment.confirmed", {"shipment_id": str(world.shipment_a.id), "appointment_id": str(aid)})
    await project()
    assert "SLOT-T1" in (await notes())[0].title


async def test_outbox_shipment_without_carrier_only_notifies_internal_roles(client, world):
    sid = await shipment(world, "SHP-DRAFT", carrier=None, offer="draft", status="PLANNED")
    await emit("eta.stale", {"shipment_id": str(sid)})
    await emit("hold.placed", {"shipment_id": str(sid)})
    await project()
    assert [n.recipient_role for n in await notes()] == ["coordinator"]


async def test_outbox_failures_back_off_and_stop_after_max_attempts(client, world):
    await emit("hold.placed", {"shipment_id": "not-a-uuid"})
    res = await project(now=NOW)
    assert res.failed == 1
    async with async_session_factory() as db:
        ev = (await db.execute(select(OutboxEvent))).scalar_one()
        assert ev.status == "failed" and ev.attempts == 1 and ev.next_attempt_at > NOW
    assert (await project(now=NOW)).failed == 0  # not due yet
    t = NOW
    for _ in range(notif.MAX_ATTEMPTS):
        t += timedelta(hours=2)
        await project(now=t)
    async with async_session_factory() as db:
        ev = (await db.execute(select(OutboxEvent))).scalar_one()
        assert ev.status == "failed" and ev.attempts == notif.MAX_ATTEMPTS
    assert (await project(now=t + timedelta(days=1))).failed == 0  # given up


async def test_failed_event_that_becomes_valid_is_retried_and_sent(client, world):
    await emit("hold.placed", {"shipment_id": str(world.shipment_a.id)}, status="failed", attempts=1,
               next_attempt_at=NOW - timedelta(minutes=1))
    assert (await project(now=NOW)).sent == 1


async def test_run_outbox_commits_and_publishes(client, world):
    await emit("shipment.offered", {"shipment_id": str(world.shipment_a.id)})
    async with async_session_factory() as db:
        res = await notif.run_outbox(db)
    assert res.sent == 1 and len(res.to_publish) == 1 and len(await notes()) == 1


async def test_notification_writes_are_not_audited(client, world):
    from app.modules.audit.models import AuditLog

    await emit("appointment.confirmed", {"shipment_id": str(world.shipment_a.id)})
    await project()
    async with async_session_factory() as db:
        ents = {e for (e,) in (await db.execute(select(AuditLog.entity))).all()}
    assert "notifications" not in ents


# ---------------------------------------------------------------- dashboard
async def test_dashboard_numbers(client, world):
    d_busy, d_free = await driver_id("DRV-A"), None
    async with async_session_factory() as db:
        from app.modules.carriers.models import Carrier  # noqa: F401

        free = Driver(code="DRV-A2", carrier_id=world.carrier_a.id, driver_name="Free", phone="+919000000011",
                      licence_number="LIC-A2", verified_at=NOW)
        off = Driver(code="DRV-A3", carrier_id=world.carrier_a.id, driver_name="Off", phone="+919000000012",
                     licence_number="LIC-A3", driver_status="INACTIVE")
        db.add_all([free, off])
        await db.commit()
        d_free = free.id
    # SHP-A is ASSIGNED with DRV-A (busy). Add: in-transit late truck, awaiting assignment, draft (ignored), other carrier
    late = await shipment(world, "SHP-LATE", carrier=world.carrier_a, driver=d_busy, status="IN_TRANSIT")
    await shipment(world, "SHP-WAIT", carrier=world.carrier_a, status="PLANNED")
    await shipment(world, "SHP-DRAFT", carrier=world.carrier_a, status="PLANNED", offer="draft")
    s1 = await slot(world, "SLOT-D1", NOW, 60)
    await appointment(world, s1, shipment=type("S", (), {"id": late}))
    async with async_session_factory() as db:
        db.add(EtaUpdate(shipment_id=late, source_type="DRIVER_DECLARED", declared_eta_ts=NOW + timedelta(hours=3),
                         confidence_code="MEDIUM"))
        db.add(FacilityCheckin(shipment_id=world.shipment_a.id, facility_id=world.facility_a.id, gate_in_ts=NOW - timedelta(hours=5),
                               unload_start_ts=NOW - timedelta(hours=2, minutes=30), queue_state="IN_DOCK"))
        await db.commit()
    await login(client, "carrier_user")
    d = (await client.get("/api/v1/carrier/dashboard")).json()
    assert d == {"drivers_available": 1, "trucks_on_road": 1, "late_trucks": 1, "awaiting_assignment": 1,
                 "upcoming_appointments_today": 1, "detention_hours": 2.5, "unverified_drivers": 1, "shipments_total": 3}
    assert d_free is not None
    client.cookies.clear()
    await login(client, "carrier_b")
    b = (await client.get("/api/v1/carrier/dashboard")).json()
    assert b["shipments_total"] == 1 and b["trucks_on_road"] == 0 and b["detention_hours"] == 0


async def test_dashboard_carrier_param_rules(client, world):
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/carrier/dashboard", params={"carrier_id": str(world.carrier_b.id)})).status_code == 404
    assert (await client.get("/api/v1/carrier/dashboard", params={"carrier_id": str(world.carrier_a.id)})).status_code == 200
    client.cookies.clear()
    await login(client, "admin")
    a = (await client.get("/api/v1/carrier/dashboard", params={"carrier_id": str(world.carrier_a.id)})).json()
    both = (await client.get("/api/v1/carrier/dashboard")).json()
    assert a["shipments_total"] == 1 and both["shipments_total"] == 2


# ---------------------------------------------------------------- tracker
async def test_tracker_content(client, world):
    s1 = await slot(world, "SLOT-TR1", NOW + timedelta(hours=1))
    await appointment(world, s1, code="APT-TR1")
    async with async_session_factory() as db:
        db.add(EtaUpdate(shipment_id=world.shipment_a.id, source_type="DRIVER_DECLARED", declared_eta_ts=NOW + timedelta(minutes=30),
                         confidence_code="HIGH"))
        db.add(FacilityCheckin(shipment_id=world.shipment_a.id, facility_id=world.facility_a.id, gate_in_ts=NOW,
                               arrival_state="EARLY", queue_state="WAITING_EARLY"))
        db.add(Escalation(shipment_id=world.shipment_a.id, reason_code="NO_FEASIBLE_SLOT", handoff_record={}))
        await db.commit()
    await login(client, "carrier_user")
    page = (await client.get("/api/v1/carrier/tracker")).json()
    assert page["total"] == 1
    r = page["items"][0]
    assert r["code"] == "SHP-A" and r["load"] == {"required_dock_type": "ANY", "temperature_control_required": False, "weight_kg": 5000}
    assert r["vehicle"]["registration_number"] == "RJ14-A" and r["driver"] == {**r["driver"], "name": "Driver A", "language": "en"}
    assert r["facility"]["code"] == "FAC-A"
    assert r["appointment"]["slot_code"] == "SLOT-TR1" and r["appointment"]["dock_code"] == "D1" and r["appointment"]["status"] == "CONFIRMED"
    assert r["eta"]["declared_by"] == "driver" and r["eta"]["confidence"] == "HIGH"
    assert r["checkin"] == {**r["checkin"], "arrival_state": "EARLY", "queue_state": "WAITING_EARLY"}
    assert r["escalation"] == {"status": "open", "reason_code": "NO_FEASIBLE_SLOT"} and r["hold_state"] == "none"


@pytest.mark.parametrize("setup,expected", [
    ("held", "held"), ("pending", "pending_confirmation"), ("waiting", "request_waiting"), ("suggested", "request_suggested"),
    ("none", "none")])
async def test_tracker_hold_state(client, world, setup, expected):
    s1 = await slot(world, "SLOT-H", NOW + timedelta(hours=1))
    async with async_session_factory() as db:
        if setup == "held":
            db.add(SlotHold(shipment_id=world.shipment_a.id, slot_id=s1, status="active", expires_at=NOW + timedelta(minutes=10)))
        if setup in ("waiting", "suggested"):
            db.add(ApprovalRequest(shipment_id=world.shipment_a.id, status=setup))
        await db.commit()
    if setup == "pending":
        await appointment(world, s1, "PENDING_CONFIRMATION")
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/carrier/tracker")).json()["items"][0]["hold_state"] == expected


async def test_tracker_expired_hold_is_not_held(client, world):
    s1 = await slot(world, "SLOT-H2", NOW + timedelta(hours=1))
    async with async_session_factory() as db:
        db.add(SlotHold(shipment_id=world.shipment_a.id, slot_id=s1, status="active", expires_at=NOW - timedelta(minutes=1)))
        await db.commit()
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/carrier/tracker")).json()["items"][0]["hold_state"] == "none"


async def test_tracker_scope_filters_and_drafts(client, world):
    await shipment(world, "SHP-A2", carrier=world.carrier_a, status="IN_TRANSIT", offer="offered")
    await shipment(world, "SHP-DRAFT", carrier=world.carrier_a, status="PLANNED", offer="draft")
    await shipment(world, "SHP-B2", carrier=world.carrier_b, facility=world.facility_b, status="IN_TRANSIT")
    await login(client, "carrier_user")
    codes = lambda r: sorted(i["code"] for i in r.json()["items"])  # noqa: E731
    assert codes(await client.get("/api/v1/carrier/tracker")) == ["SHP-A", "SHP-A2"]  # draft and carrier B hidden
    assert codes(await client.get("/api/v1/carrier/tracker", params={"status": "IN_TRANSIT"})) == ["SHP-A2"]
    assert codes(await client.get("/api/v1/carrier/tracker", params={"q": "A2"})) == ["SHP-A2"]
    assert codes(await client.get("/api/v1/carrier/tracker", params={"facility_id": str(world.facility_b.id)})) == []
    assert codes(await client.get("/api/v1/carrier/tracker", params={"limit": 1})) == ["SHP-A"]
    assert (await client.get("/api/v1/carrier/tracker", params={"carrier_id": str(world.carrier_b.id)})).status_code == 404
    client.cookies.clear()
    await login(client, "carrier_b")
    assert codes(await client.get("/api/v1/carrier/tracker")) == ["SHP-B", "SHP-B2"]
    client.cookies.clear()
    await login(client, "coordinator")
    assert codes(await client.get("/api/v1/carrier/tracker")) == ["SHP-A", "SHP-A2", "SHP-B", "SHP-B2"]
    assert codes(await client.get("/api/v1/carrier/tracker", params={"carrier_id": str(world.carrier_b.id)})) == ["SHP-B", "SHP-B2"]


async def test_tracker_is_read_only(client, world):
    await login(client, "carrier_user")
    for method in ("post", "put", "patch", "delete"):
        assert (await getattr(client, method)("/api/v1/carrier/tracker")).status_code == 405


# ---------------------------------------------------------------- slot changes
async def test_slot_changes_ordering_content_and_scope(client, world):
    s1 = await slot(world, "SLOT-C1", NOW + timedelta(hours=1))
    s2 = await slot(world, "SLOT-C2", NOW + timedelta(hours=2))
    s3 = await slot(world, "SLOT-C3", NOW + timedelta(hours=3))
    sb = await slot(world, "SLOT-CB", NOW + timedelta(hours=4), dock_code="D2")
    await appointment(world, s1, "CANCELLED", code="A1", booked_at=NOW - timedelta(hours=4), cancelled_at=NOW - timedelta(hours=3),
                      cancellation_reason="REPLACED", is_current=False)
    await appointment(world, s2, "CONFIRMED", code="A2", confirmed_at=NOW - timedelta(hours=2))
    await appointment(world, sb, "CONFIRMED", shipment=type("S", (), {"id": world.shipment_b.id}), code="AB", confirmed_at=NOW)
    async with async_session_factory() as db:
        db.add(SlotHold(shipment_id=world.shipment_a.id, slot_id=s3, status="active", expires_at=NOW + timedelta(minutes=10),
                        created_at=NOW - timedelta(hours=1)))
        db.add(ApprovalRequest(shipment_id=world.shipment_a.id, status="rejected", reason="Dock under repair", slot_id=s3,
                               decided_at=NOW - timedelta(minutes=30)))
        db.add(Escalation(shipment_id=world.shipment_a.id, reason_code="NO_FEASIBLE_SLOT", handoff_record={"summary": "No slot found"},
                          created_at=NOW - timedelta(minutes=5)))
        await db.commit()
    await login(client, "carrier_user")
    ch = (await client.get("/api/v1/carrier/slot-changes")).json()
    assert [c["kind"] for c in ch] == ["escalated", "rejected", "held", "confirmed", "replaced"]
    assert ch == sorted(ch, key=lambda c: c["ts"], reverse=True)
    assert ch[0]["reason"] == "No slot found" and ch[1]["reason"] == "Dock under repair" and ch[1]["slot_code"] == "SLOT-C3"
    assert ch[3]["slot_code"] == "SLOT-C2" and ch[4]["reason"] == "REPLACED"
    assert all(c["shipment_code"] == "SHP-A" for c in ch)  # carrier B's confirmed booking never appears
    assert len((await client.get("/api/v1/carrier/slot-changes", params={"limit": 2})).json()) == 2
    client.cookies.clear()
    await login(client, "carrier_b")
    assert [c["kind"] for c in (await client.get("/api/v1/carrier/slot-changes")).json()] == ["confirmed"]


# ---------------------------------------------------------------- reports
async def test_reports_kinds_and_csv(client, world):
    async with async_session_factory() as db:
        (await db.get(Shipment, world.shipment_a.id)).original_eta_ts = NOW
        db.add(EtaUpdate(shipment_id=world.shipment_a.id, source_type="DRIVER_DECLARED",
                         declared_eta_ts=NOW + timedelta(minutes=95), confidence_code="MEDIUM"))
        db.add(FacilityCheckin(shipment_id=world.shipment_a.id, facility_id=world.facility_a.id, gate_in_ts=NOW,
                               unload_start_ts=NOW + timedelta(minutes=45), queue_state="IN_DOCK"))
        await db.commit()
    await login(client, "carrier_user")
    day = NOW.date().isoformat()
    q = {"date_from": (NOW - timedelta(days=1)).date().isoformat(), "date_to": (NOW + timedelta(days=1)).date().isoformat()}
    ships = (await client.get("/api/v1/reports/carrier", params={**q, "kind": "shipments"})).json()
    assert ships["columns"][0] == "shipment" and [r["shipment"] for r in ships["rows"]] == ["SHP-A"]
    delays = (await client.get("/api/v1/reports/carrier", params={**q, "kind": "delays"})).json()
    assert delays["rows"][0]["delay_min"] == 95 and delays["rows"][0]["eta_source"] == "DRIVER_DECLARED"
    det = (await client.get("/api/v1/reports/carrier", params={**q, "kind": "detention"})).json()
    assert det["rows"][0]["detention_min"] == 45 and det["rows"][0]["facility"] == "FAC-A"
    csv = await client.get("/api/v1/reports/carrier/export.csv", params={**q, "kind": "detention"})
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0] == "shipment,facility,gate_in,unload_start,detention_min"
    assert "SHP-A" in csv.text and day
    empty = (await client.get("/api/v1/reports/carrier", params={"kind": "shipments", "date_from": "2020-01-01", "date_to": "2020-01-02"})).json()
    assert empty["rows"] == [] and empty["columns"]


async def test_reports_validation_and_scope(client, world):
    q = {"date_from": "2026-01-01", "date_to": "2027-12-31"}
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/reports/carrier", params={**q, "kind": "shipments"})).status_code == 422
    assert (await client.get("/api/v1/reports/carrier", params={"date_from": "2026-01-01", "date_to": "2026-02-01", "kind": "nope"})).status_code == 422
    assert (await client.get("/api/v1/reports/carrier", params={"date_from": "2026-02-01", "date_to": "2026-01-01", "kind": "delays"})).status_code == 422
    wide = {"date_from": (NOW - timedelta(days=2)).date().isoformat(), "date_to": (NOW + timedelta(days=2)).date().isoformat(), "kind": "shipments"}
    assert [r["shipment"] for r in (await client.get("/api/v1/reports/carrier", params=wide)).json()["rows"]] == ["SHP-A"]
    assert (await client.get("/api/v1/reports/carrier", params={**wide, "carrier_id": str(world.carrier_b.id)})).status_code == 404
    client.cookies.clear()
    await login(client, "admin")
    assert len((await client.get("/api/v1/reports/carrier", params=wide)).json()["rows"]) == 2
    only_b = (await client.get("/api/v1/reports/carrier", params={**wide, "carrier_id": str(world.carrier_b.id)})).json()
    assert [r["shipment"] for r in only_b["rows"]] == ["SHP-B"]


# ---------------------------------------------------------------- permission matrix
PORTAL_PATHS = ["/api/v1/carrier/dashboard", "/api/v1/carrier/tracker", "/api/v1/carrier/slot-changes",
                "/api/v1/reports/carrier?kind=shipments&date_from=2026-01-01&date_to=2026-01-31"]


@pytest.mark.parametrize("path", PORTAL_PATHS)
@pytest.mark.parametrize("role,code", [("admin", 200), ("coordinator", 200), ("carrier_user", 200), ("facility_planner", 403)])
async def test_carrier_portal_permissions(client, world, path, role, code):
    await login(client, role)
    assert (await client.get(path)).status_code == code


@pytest.mark.parametrize("path", PORTAL_PATHS)
async def test_carrier_portal_requires_authentication(client, world, path):
    assert (await client.get(path)).status_code == 401


@pytest.mark.parametrize("role", ["admin", "coordinator", "facility_planner", "carrier_user"])
async def test_every_role_can_open_its_own_notifications(client, world, role):
    await login(client, role)
    assert (await client.get("/api/v1/notifications")).status_code == 200
