import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import events
from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.core.security import hash_password
from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.docks.models import Dock
from app.modules.drivers.models import Driver
from app.modules.eta import service as eta_service
from app.modules.notifications.models import OperationalMessage, OutboxEvent
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.users.models import User
from app.modules.whatsapp.models import ChatMessage, ChatThread
from tests.conftest import PASSWORD, login

BASE = "/api/v1/coordinator"
T0 = datetime(2030, 1, 10, tzinfo=UTC)
MSG0 = datetime(2026, 1, 1, tzinfo=UTC)  # chat history is in the past so a live reply (now) sorts after it


def at(h, m=0, day=T0):
    return day.replace(hour=h, minute=m)


async def mk_thread(driver_id, shipment_id=None, status="OPEN", intent="UNKNOWN", code=None):
    async with async_session_factory() as db:
        t = ChatThread(code=code or f"THR{uuid.uuid4().hex[:6]}", driver_id=driver_id, shipment_id=shipment_id,
                       opened_at=at(1, day=MSG0), thread_status=status, thread_intent=intent)
        db.add(t)
        await db.commit()
        return t.id


async def mk_msg(thread_id, text, minute, sender="DRIVER", intent=None, review=False, dup=False):
    async with async_session_factory() as db:
        db.add(ChatMessage(code=f"M{uuid.uuid4().hex[:8]}", thread_id=thread_id, sender_type=sender, message_text=text,
                           message_ts=at(2, minute, MSG0), parsed_intent=intent, requires_human_review=review, is_duplicate=dup))
        await db.commit()


async def second_coordinator(client):
    async with async_session_factory() as db:
        db.add(User(email="coord2@test.io", full_name="Second Coordinator", role="coordinator", status="active",
                    password_hash=hash_password(PASSWORD)))
        await db.commit()
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    r = await client.post("/api/v1/auth/login", json={"email": "coord2@test.io", "password": PASSWORD})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


async def outbox(kind):
    async with async_session_factory() as db:
        return list((await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == kind))).scalars().all())


# ---------------- conversations ----------------
async def test_threads_list_order_filters_and_last_message(client, world):
    ta = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id, "OPEN", "REPORT_DELAY", "THR-A")
    tb = await mk_thread(world.shipment_b.driver_id, None, "ESCALATED", "UNKNOWN", "THR-B")
    await mk_msg(ta, "Truck broke down", 5, intent="REPORT_DELAY", review=True)
    await mk_msg(ta, "Please share a new ETA", 9, sender="AGENT")
    await mk_msg(tb, "Hello?", 30)
    await login(client, "coordinator")
    page = (await client.get(f"{BASE}/threads")).json()
    assert page["total"] == 2 and [i["code"] for i in page["items"]] == ["THR-B", "THR-A"]  # newest message first
    a = next(i for i in page["items"] if i["code"] == "THR-A")
    assert a["last_message_text"] == "Please share a new ETA" and a["requires_review"] is True
    assert a["shipment_code"] == "SHP-A" and a["driver_name"] == "Driver A" and a["bot_paused"] is False
    b = next(i for i in page["items"] if i["code"] == "THR-B")
    assert b["shipment_code"] is None and b["requires_review"] is False
    assert (await client.get(f"{BASE}/threads", params={"status": "ESCALATED"})).json()["total"] == 1
    assert (await client.get(f"{BASE}/threads", params={"q": "driver a"})).json()["total"] == 1
    assert (await client.get(f"{BASE}/threads", params={"q": "SHP-A"})).json()["total"] == 1
    assert (await client.get(f"{BASE}/threads", params={"taken_over": "true"})).json()["total"] == 0
    assert (await client.get(f"{BASE}/threads", params={"limit": 1, "offset": 1})).json()["items"][0]["code"] == "THR-A"


async def test_thread_without_messages_still_listed(client, world):
    await mk_thread(world.shipment_a.driver_id, code="THR-EMPTY")
    await login(client, "coordinator")
    item = (await client.get(f"{BASE}/threads")).json()["items"][0]
    assert item["last_message_text"] is None and item["last_message_ts"] is None


async def test_thread_messages_ascending_with_flags(client, world):
    t = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id)
    await mk_msg(t, "second", 20)
    await mk_msg(t, "first", 10, intent="REPORT_DELAY")
    await mk_msg(t, "first", 11, dup=True)
    await login(client, "coordinator")
    d = (await client.get(f"{BASE}/threads/{t}/messages")).json()
    assert [m["text"] for m in d["messages"]] == ["first", "first", "second"]
    assert d["messages"][1]["is_duplicate"] is True and d["messages"][0]["parsed_intent"] == "REPORT_DELAY"
    assert all(m["translation"] is None for m in d["messages"]) and d["thread"]["id"] == str(t)
    assert (await client.get(f"{BASE}/threads/{uuid.uuid4()}/messages")).status_code == 404


async def test_takeover_handback_reply_flow_and_outbox(client, world):
    t = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id)
    await mk_msg(t, "Where do I go?", 1)
    await login(client, "coordinator")
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "hi"})).status_code == 409  # not taken over yet
    r = await client.post(f"{BASE}/threads/{t}/takeover")
    assert r.status_code == 200 and r.json()["bot_paused"] is True and r.json()["taken_over_by"]["name"] == "Coordinator"
    assert (await client.post(f"{BASE}/threads/{t}/takeover")).status_code == 200  # idempotent for the owner
    rep = await client.post(f"{BASE}/threads/{t}/reply", json={"text": "  Go to gate 2 please  "})
    assert rep.status_code == 201
    body = rep.json()
    assert body["message"]["sender_type"] == "OPERATIONS" and body["message"]["text"] == "Go to gate 2 please"
    assert body["deliverable"] is False  # seeded test drivers are not WhatsApp-verified
    ev = await outbox("whatsapp.send")
    assert len(ev) == 1 and ev[0].payload["text"] == "Go to gate 2 please" and ev[0].payload["thread_id"] == str(t)
    msgs = (await client.get(f"{BASE}/threads/{t}/messages")).json()["messages"]
    assert msgs[-1]["text"] == "Go to gate 2 please" and msgs[-1]["sender_type"] == "OPERATIONS"
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": ""})).status_code == 422
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "x" * 1001})).status_code == 422
    assert (await client.post(f"{BASE}/threads/{t}/handback")).json()["bot_paused"] is False
    assert (await client.post(f"{BASE}/threads/{t}/handback")).status_code == 409  # already with the bot
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "again"})).status_code == 409


async def test_second_coordinator_is_blocked_and_cannot_hand_back_or_reply(client, world):
    t = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id)
    await login(client, "coordinator")
    await client.post(f"{BASE}/threads/{t}/takeover")
    await second_coordinator(client)
    r = await client.post(f"{BASE}/threads/{t}/takeover")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CLAIMED"
    assert r.json()["error"]["details"]["claimed_by"]["name"] == "Coordinator"
    h = await client.post(f"{BASE}/threads/{t}/handback")
    assert h.status_code == 409 and h.json()["error"]["code"] == "NOT_OWNER"
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "hello"})).status_code == 409
    assert (await client.get(f"{BASE}/threads", params={"taken_over": "true"})).json()["total"] == 1
    assert (await outbox("whatsapp.send")) == []


async def test_reply_deliverable_when_driver_verified_and_opted_in(client, world):
    async with async_session_factory() as db:
        d = await db.get(Driver, world.shipment_a.driver_id)
        d.whatsapp_number, d.verified_at, d.whatsapp_opt_in = "+919800000001", datetime.now(UTC), True
        await db.commit()
    t = await mk_thread(world.shipment_a.driver_id)
    await login(client, "coordinator")
    await client.post(f"{BASE}/threads/{t}/takeover")
    rep = (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "ok"})).json()
    assert rep["deliverable"] is True
    assert (await outbox("whatsapp.send"))[0].payload["to"] == "+919800000001"
    async with async_session_factory() as db:
        d = await db.get(Driver, world.shipment_a.driver_id)
        d.whatsapp_opt_in = False
        await db.commit()
    assert (await client.post(f"{BASE}/threads/{t}/reply", json={"text": "ok again"})).json()["deliverable"] is False


async def test_draft_language_and_intent(client, world):
    await login(client, "coordinator")
    delay = await mk_thread(world.shipment_a.driver_id, intent="REPORT_DELAY")
    d = (await client.get(f"{BASE}/threads/{delay}/draft")).json()
    assert d["language"] == "en" and d["source"] == "rules" and "new expected arrival time" in d["text"] and "Driver" in d["text"]
    async with async_session_factory() as db:
        drv = await db.get(Driver, world.shipment_b.driver_id)
        drv.preferred_language = "hi"
        a = await db.get(Driver, world.shipment_a.driver_id)
        a.preferred_language = "ta"  # unsupported draft language falls back to English
        await db.commit()
    hi = await mk_thread(world.shipment_b.driver_id, intent="ASK_SLOT_OPTIONS")
    h = (await client.get(f"{BASE}/threads/{hi}/draft")).json()
    assert h["language"] == "hi" and "डॉक स्लॉट" in h["text"]
    unknown = await mk_thread(world.shipment_a.driver_id, intent="UNKNOWN")
    u = (await client.get(f"{BASE}/threads/{unknown}/draft")).json()
    assert u["language"] == "en" and "How can we help" in u["text"]
    await mk_msg(unknown, "late by two hours", 3, intent="REPORT_DELAY")  # the last parsed driver intent wins
    assert "new expected arrival time" in (await client.get(f"{BASE}/threads/{unknown}/draft")).json()["text"]


# ---------------- live board ----------------
async def mk_shipment(world, code, status, priority="NORMAL"):
    s = world.shipment_a
    async with async_session_factory() as db:
        sh = Shipment(code=code, order_reference=f"ORD-{code}", carrier_id=s.carrier_id, driver_id=s.driver_id,
                      vehicle_id=s.vehicle_id, origin_name="O", origin_city="Delhi", destination_facility_id=world.facility_a.id,
                      customer_name="C", product_category="G", load_weight_kg=1000, planned_departure_ts=at(0),
                      original_eta_ts=at(4), expected_unload_min=60, current_status=status, offer_status="accepted",
                      priority_code=priority)
        db.add(sh)
        await db.commit()
        return sh.id


async def mk_booking(world, shipment_id, start, dock=None, status="CONFIRMED"):
    async with async_session_factory() as db:
        if dock is None:
            dock = Dock(code=f"D{uuid.uuid4().hex[:5]}", facility_id=world.facility_a.id, dock_code=f"K{uuid.uuid4().hex[:4]}",
                        dock_type="STANDARD", max_vehicle_weight_kg=30000)
            db.add(dock)
            await db.flush()
        slot = AppointmentSlot(code=f"S{uuid.uuid4().hex[:8]}", facility_id=world.facility_a.id, dock_id=dock.id,
                               slot_start_ts=start, slot_end_ts=start + timedelta(hours=1))
        db.add(slot)
        await db.flush()
        db.add(Appointment(code=f"A{uuid.uuid4().hex[:8]}", shipment_id=shipment_id, slot_id=slot.id,
                           appointment_status=status, booking_source="PLANNER", booked_at=at(0)))
        await db.commit()
        return slot.code, dock.dock_code


async def set_eta(shipment_id, when, confidence="MEDIUM"):
    async with async_session_factory() as db:
        await eta_service.record_update(db, shipment_id, source_type="DRIVER_DECLARED", declared_eta_ts=when, confidence=confidence)
        await db.commit()


async def test_board_stages(client, world):
    day = "2030-01-10"
    travelling = await mk_shipment(world, "SHP-TRV", "IN_TRANSIT", "LOW")
    late = await mk_shipment(world, "SHP-LATE", "IN_TRANSIT", "CRITICAL")
    yard = await mk_shipment(world, "SHP-YARD", "AT_GATE")
    dock = await mk_shipment(world, "SHP-DOCK", "IN_DOCK")
    done = await mk_shipment(world, "SHP-DONE", "COMPLETED")
    other_day = await mk_shipment(world, "SHP-OTHER", "IN_TRANSIT")
    draft = await mk_shipment(world, "SHP-NOACC", "IN_TRANSIT")
    await set_eta(travelling, at(4))                      # 09:30 IST
    await mk_booking(world, travelling, at(5))            # slot 10:30 IST: ETA before slot -> travelling
    await set_eta(late, at(7))
    await mk_booking(world, late, at(5, 30))              # ETA 90 min after slot start -> late
    await set_eta(yard, at(4))
    await set_eta(dock, at(4))
    code, dock_code = await mk_booking(world, dock, at(4), status="IN_PROGRESS")
    await set_eta(done, at(3))
    await set_eta(other_day, datetime(2030, 1, 20, 4, tzinfo=UTC))
    await set_eta(draft, at(4))
    async with async_session_factory() as db:
        sh = await db.get(Shipment, draft)
        sh.offer_status = "offered"
        db.add(FacilityCheckin(shipment_id=yard, facility_id=world.facility_a.id, gate_in_ts=at(3), queue_state="WAITING_EARLY"))
        db.add(FacilityCheckin(shipment_id=dock, facility_id=world.facility_a.id, gate_in_ts=at(3), queue_state="IN_DOCK"))
        db.add(FacilityCheckin(shipment_id=done, facility_id=world.facility_a.id, gate_in_ts=at(2), unload_end_ts=at(3, 30),
                               queue_state="COMPLETED"))
        await db.commit()
    await login(client, "coordinator")
    out = (await client.get(f"{BASE}/board", params={"date": day})).json()
    stage = {k: [r["code"] for r in v] for k, v in out["stages"].items()}
    assert stage["travelling"] == ["SHP-TRV"]
    assert stage["late"] == ["SHP-LATE"]
    assert stage["in_yard"] == ["SHP-YARD"] and stage["unloading"] == ["SHP-DOCK"] and stage["done"] == ["SHP-DONE"]
    assert out["counts"] == {"travelling": 1, "late": 1, "in_yard": 1, "unloading": 1, "done": 1}
    late_row = out["stages"]["late"][0]
    assert late_row["late_min"] == 90 and late_row["carrier_name"] == "Carrier A" and late_row["facility_code"] == "FAC-A"
    assert late_row["slot_code"] and late_row["priority_code"] == "CRITICAL"
    assert out["stages"]["unloading"][0]["dock_code"] == dock_code
    only_b = (await client.get(f"{BASE}/board", params={"date": day, "facility_id": str(world.facility_b.id)})).json()
    assert sum(only_b["counts"].values()) == 0
    default_day = (await client.get(f"{BASE}/board")).json()  # today in facility time: the 2030 shipments are not on it
    assert "SHP-TRV" not in [r["code"] for r in default_day["stages"]["travelling"]]


async def test_board_marks_overdue_eta_as_late(client, world):
    stale = await mk_shipment(world, "SHP-STALE", "ASSIGNED", "HIGH")
    fresh = await mk_shipment(world, "SHP-FRESH", "ASSIGNED")
    await set_eta(stale, datetime(2026, 1, 5, 4, tzinfo=UTC))      # ETA long gone, never checked in
    await set_eta(fresh, datetime.now(UTC))  # same local day as the default board date, whatever the hour
    await login(client, "coordinator")
    out = (await client.get(f"{BASE}/board", params={"date": "2026-01-05"})).json()
    assert [r["code"] for r in out["stages"]["late"]] == ["SHP-STALE"] and out["stages"]["late"][0]["late_min"] > 15
    today = (await client.get(f"{BASE}/board")).json()
    codes = [r["code"] for r in today["stages"]["travelling"]]
    assert "SHP-FRESH" in codes and "SHP-STALE" not in codes  # the fixture shipments SHP-A/SHP-B (ETA now) show too


# ---------------- handover ----------------
async def test_handover_draft_save_and_list(client, world):
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        req = ApprovalRequest(shipment_id=world.shipment_a.id, status="waiting", reason_code="REPLAN_DOCK_EVENT")
        done = ApprovalRequest(shipment_id=world.shipment_b.id, status="approved", decided_at=now)
        esc = Escalation(shipment_id=world.shipment_a.id, reason_code="NO_FEASIBLE_SLOT", handoff_record={}, status="open")
        db.add_all([req, done, esc, OperationalMessage(
            shipment_id=world.shipment_a.id, channel="WHATSAPP", sender_address="ops", recipient_address="+91",
            message_body="x", sent_at=now, delivery_status="FAILED")])
        await db.commit()
    await login(client, "coordinator")
    d = (await client.get(f"{BASE}/handover/draft")).json()
    snap = d["snapshot"]
    assert snap["source"] == "rules" and [r["shipment_code"] for r in snap["open_requests"]] == ["SHP-A"]
    assert snap["open_escalations"][0]["reason_code"] == "NO_FEASIBLE_SLOT"
    assert snap["failed_messages"] == 1 and snap["decisions_made_since"] == 1 and snap["pending_confirmations"] == 0
    assert "Open requests (1)" in d["summary"] and "NO_FEASIBLE_SLOT" in d["summary"]
    since = (now - timedelta(hours=1)).isoformat()
    body = {"shift_started_at": since, "summary": "Edited by the coordinator: all quiet after 18:00.", "notes": "Call Jaipur gate",
            "snapshot": {"open_requests": [], "bogus": True}}
    r = await client.post(f"{BASE}/handover", json=body)
    assert r.status_code == 201
    saved = r.json()
    assert saved["author_name"] == "Coordinator" and saved["summary"].startswith("Edited") and saved["notes"] == "Call Jaipur gate"
    assert len(saved["snapshot"]["open_requests"]) == 1 and "bogus" not in saved["snapshot"]  # recomputed server-side
    assert (await client.post(f"{BASE}/handover", json={**body, "summary": "short"})).status_code == 422
    listing = (await client.get(f"{BASE}/handover")).json()
    assert len(listing) == 1 and listing[0]["id"] == saved["id"]
    async with async_session_factory() as db:
        assert (await db.execute(select(SlotHold))).first() is None


async def test_handover_roles(client, world):
    body = {"shift_started_at": datetime.now(UTC).isoformat(), "summary": "Admin tries to write a handover"}
    await login(client, "admin")
    assert (await client.get(f"{BASE}/handover/draft")).status_code == 200
    assert (await client.get(f"{BASE}/handover")).status_code == 200
    assert (await client.post(f"{BASE}/handover", json=body)).status_code == 403


# ---------------- activity ----------------
async def test_activity_shows_only_own_actions_with_outcomes(client, world):
    t = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id)
    await login(client, "coordinator")
    await client.post(f"{BASE}/threads/{t}/takeover")
    await client.post(f"{BASE}/threads/{t}/reply", json={"text": "On my way to help"})
    await client.post(f"{BASE}/threads/{t}/handback")
    await client.post(f"{BASE}/handover", json={"shift_started_at": datetime.now(UTC).isoformat(),
                                                 "summary": "Quiet shift, nothing open at all."})
    mine = (await client.get(f"{BASE}/activity")).json()
    summaries = [a["summary"] for a in mine]
    assert "Took over a conversation" in summaries and "Handed a conversation back to the bot" in summaries
    assert "Sent a reply to a driver" in summaries and "Saved a shift handover" in summaries
    assert {a["entity"] for a in mine} <= {"chat_threads", "chat_messages", "handover_records"}
    assert next(a for a in mine if a["entity"] == "chat_messages")["outcome"] == "sent"
    assert next(a for a in mine if a["entity"] == "chat_threads")["outcome"] == "OPEN"
    assert [a["ts"] for a in mine] == sorted([a["ts"] for a in mine], reverse=True)
    assert len((await client.get(f"{BASE}/activity", params={"limit": 2})).json()) == 2
    await second_coordinator(client)
    assert (await client.get(f"{BASE}/activity")).json() == []  # the second coordinator has done nothing
    await login_other(client, "admin")
    assert (await client.get(f"{BASE}/activity")).json() == []  # nor does admin see coordinators' actions


async def login_other(client, who):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await login(client, who)


# ---------------- roles, SSE ----------------
async def test_role_matrix_for_desk_endpoints(client, world):
    t = await mk_thread(world.shipment_a.driver_id)
    reads = [f"{BASE}/threads", f"{BASE}/threads/{t}/messages", f"{BASE}/threads/{t}/draft", f"{BASE}/board",
             f"{BASE}/handover/draft", f"{BASE}/handover", f"{BASE}/activity"]
    writes = [(f"{BASE}/threads/{t}/takeover", None), (f"{BASE}/threads/{t}/handback", None),
              (f"{BASE}/threads/{t}/reply", {"text": "hello"})]
    for who, can_read in (("coordinator", True), ("admin", True), ("facility_planner", False), ("carrier_user", False)):
        await login_other(client, who)
        for url in reads:
            assert (await client.get(url)).status_code == (200 if can_read else 403), (who, url)
        for url, body in writes:
            r = await client.post(url, json=body) if body else await client.post(url)
            if who == "coordinator":
                assert r.status_code in (200, 201, 409), (who, url)
            else:
                assert r.status_code == 403, (who, url, r.status_code)
    assert (await client.get(f"{BASE}/threads")).status_code == 403
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    assert (await client.get(f"{BASE}/threads")).status_code == 401


async def test_inbox_changed_event_published(client, world):
    t = await mk_thread(world.shipment_a.driver_id, world.shipment_a.id)
    redis = get_redis()
    try:
        await redis.delete(events.STREAM)
        await login(client, "coordinator")
        await client.post(f"{BASE}/threads/{t}/takeover")
        await client.post(f"{BASE}/threads/{t}/reply", json={"text": "hello driver"})
        await client.post(f"{BASE}/threads/{t}/handback")
        entries = await redis.xrange(events.STREAM)
        kinds = [e[1]["type"] for e in entries]
        assert kinds == ["inbox.changed"] * 3
        assert {e[1]["facility_id"] for e in entries} == {""}  # unscoped: visible to coordinators and admins only
        gen = events.stream_for(redis, "carrier_user", set(), world.carrier_a.id, last_id="0-0", block_ms=100)
        got = []

        async def drain():
            async for chunk in gen:
                if chunk.startswith("id:"):
                    got.append(chunk)

        import asyncio

        try:
            await asyncio.wait_for(drain(), 1)
        except TimeoutError:
            pass
        assert got == []  # carriers never see inbox events
    finally:
        await redis.delete(events.STREAM)
        await redis.aclose()
