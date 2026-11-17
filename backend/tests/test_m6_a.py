"""Milestone 6 part A: coordinator inbox, locks, request detail + recommendation, escalate, competing, escalations."""
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.modules.booking import engine
from app.modules.booking.models import ApprovalRequest, Escalation, SlotHold
from app.modules.coordinator.recommend import HeldFacts, OptionFacts, recommend
from app.modules.exceptions.models import DriverException
from app.modules.notifications.models import OperationalMessage, OutboxEvent
from app.modules.whatsapp.models import ChatMessage, ChatThread
from app.modules.eta import service as eta_service
from tests.conftest import login
from tests.m4_helpers import at, m4, new_shipment, orm_book  # noqa: F401

API = "/api/v1/coordinator"
NOW = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)


async def outbox(kind):
    async with async_session_factory() as db:
        return list((await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == kind))).scalars().all())


async def make_request(m4_, world, tag="R1", *, priority="NORMAL", hold=True, slot=("D1", "09:00"), reason_code=None,
                       exception=False, eta=None):
    sh = await new_shipment(world, tag, priority=priority, eta=eta)
    exc_id = None
    async with async_session_factory() as db:
        if exception:
            th = ChatThread(code=f"THX{tag}", driver_id=sh.driver_id, shipment_id=sh.id, opened_at=NOW, thread_status="OPEN",
                            thread_intent="REPORT_DELAY")
            db.add(th)
            await db.flush()
            db.add(ChatMessage(code=f"MSX{tag}", thread_id=th.id, sender_type="DRIVER", message_text="Truck pura kharab ho gaya, 2 ghante late",
                               message_ts=NOW, requires_human_review=True))
            exc = DriverException(code=f"EXX{tag}", shipment_id=sh.id, driver_id=sh.driver_id, thread_id=th.id, exception_type="BREAKDOWN",
                                  reported_at=NOW, reported_delay_min=120, declared_eta_ts=at("09:00"), severity_code="HIGH",
                                  exception_status="OPEN", description="Breakdown, about 2 hours late", latest_acceptable_ts=at("20:00"))
            db.add(exc)
            await db.flush()
            exc_id = exc.id
        hold_id = None
        if hold:
            h = await engine.place_hold(db, sh.id, [m4_.slot(*slot).id], exception_id=exc_id)
            hold_id = h.id
        r = await engine.create_request(db, sh.id, hold_id=hold_id, exception_id=exc_id, reason_code=reason_code)
        await db.commit()
        return sh, r.id, hold_id


async def as_coord(client, who="coordinator"):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await login(client, who)


# ---------------------------------------------------------------- pure recommendation
def _opt(h=9):
    return OptionFacts(["s1"], ["D1-0900"], NOW.replace(hour=h), False)


def rec(**kw):
    base = dict(held=None, options=[_opt()], eta_ts=NOW, eta_confidence="HIGH", eta_range=False, requires_human_review=False,
                priority="NORMAL", replan=False, current_slot_code="D2-0800", now=NOW)
    return recommend(**{**base, **kw})


def test_recommend_approve_when_held_option_is_feasible():
    r = rec(held=HeldFacts(True, False, [], NOW.replace(hour=9), "D1-0900"))
    assert r.action == "approve" and r.source == "rules" and any("Releases" in i for i in r.impact)


def test_recommend_approve_flags_planner_confirmation_and_risk_flags():
    r = rec(held=HeldFacts(True, True, [], NOW.replace(hour=22), "D1-2200"), eta_confidence="LOW", eta_range=True, priority="CRITICAL",
            replan=True, eta_ts=NOW - timedelta(hours=2))
    assert r.action == "approve" and any("planner confirmation" in i for i in r.impact)
    assert {"ETA_VAGUE", "ETA_RANGE", "CRITICAL_PRIORITY", "ETA_STALE"} <= set(r.risk_flags) and any("dock event" in x for x in r.reasons)


def test_recommend_suggest_when_hold_gone_and_escalate_when_nothing():
    gone = HeldFacts(False, False, ["OCCUPIED"], NOW.replace(hour=9), "D1-0900")
    r = rec(held=gone)
    assert r.action == "suggest" and r.slot_ids == ["s1"] and any("OCCUPIED" in x for x in r.reasons)
    assert rec(held=HeldFacts(True, False, [], NOW, "D1", expired=True)).action == "suggest"
    e = rec(options=[], held=None)
    assert e.action == "escalate" and any("Do not invent" in x for x in e.reasons)
    assert rec(replan=True, held=None).action == "suggest"


def test_recommend_hold_for_vague_eta_without_hold():
    r = rec(requires_human_review=True, eta_confidence="LOW")
    assert r.action == "hold" and "ETA_VAGUE" in r.risk_flags


# ---------------------------------------------------------------- locks
async def test_claim_blocks_second_coordinator_and_shows_owner(client, world, m4):
    sh, rid, _ = await make_request(m4, world)
    await as_coord(client)
    c = await client.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})
    assert c.status_code == 200 and c.json()["claimed_by"]["name"] == "Coordinator"
    assert (await client.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})).status_code == 200  # owner renews
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.modules.users.models import User

    async with async_session_factory() as db:
        from app.core.security import hash_password

        db.add(User(email="coord2@test.io", full_name="Second Coordinator", role="coordinator", status="active",
                    password_hash=hash_password("CorrectHorse-Battery9")))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        r = await other.post("/api/v1/auth/login", json={"email": "coord2@test.io", "password": "CorrectHorse-Battery9"})
        assert r.status_code == 200
        other.headers["X-CSRF-Token"] = other.cookies.get("csrf_token")
        blocked = await other.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})
        assert blocked.status_code == 409 and blocked.json()["error"]["details"]["claimed_by"]["name"] == "Coordinator"
        assert (await other.post(f"/api/v1/booking/requests/{rid}/approve")).status_code == 409  # decisions are blocked too
        assert (await other.post(f"/api/v1/booking/requests/{rid}/reject", json={"reason": "not mine"})).json()["error"]["code"] == "CLAIMED"
        assert (await other.post(f"{API}/release", json={"kind": "request", "id": str(rid)})).status_code == 204  # not the owner: no-op
        assert (await other.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})).status_code == 409
        await client.post(f"{API}/release", json={"kind": "request", "id": str(rid)})
        assert (await other.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})).status_code == 200
    assert (await client.post(f"{API}/claim", json={"kind": "nope", "id": str(rid)})).status_code == 422


async def test_lock_expires_by_ttl(client, world, m4):
    sh, rid, _ = await make_request(m4, world)
    await as_coord(client)
    await client.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})
    redis = get_redis()
    try:
        assert 0 < await redis.ttl(f"lock:request:{rid}") <= 600
        await redis.pexpire(f"lock:request:{rid}", 1)
    finally:
        await redis.aclose()
    import asyncio

    await asyncio.sleep(0.05)
    assert (await client.get(f"{API}/inbox", params={"kind": "request"})).json()["items"][0]["claimed_by"] is None


# ---------------------------------------------------------------- inbox
async def test_inbox_collects_every_kind_sorted_by_priority_then_age(client, world, m4):
    low, r_low, _ = await make_request(m4, world, "LOW", priority="LOW", slot=("D1", "09:00"))
    crit, r_crit, _ = await make_request(m4, world, "CRIT", priority="CRITICAL", slot=("D1", "10:00"))
    exc_ship, r_exc, _ = await make_request(m4, world, "EXC", slot=("D1", "11:00"), exception=True)
    async with async_session_factory() as db:
        hold_ship = await new_shipment(world, "EXPIRING")
        h = await engine.place_hold(db, hold_ship.id, [m4.slot("D2", "09:00").id], ttl_minutes=3)
        await engine.escalate(db, crit.id, "NO_FEASIBLE_SLOT", {"summary": "nothing fits"})
        db.add(OperationalMessage(shipment_id=low.id, channel="EMAIL", sender_address="ops@x", recipient_address="gate@dc.in",
                                  subject="Slot", message_body="b", sent_at=datetime.now(UTC), delivery_status="FAILED"))
        await eta_service.record_update(db, hold_ship.id, source_type="DRIVER_DECLARED", declared_eta_ts=at("11:00"), confidence="LOW")
        await db.commit()
        hold_id = h.id
    await as_coord(client)
    body = (await client.get(f"{API}/inbox")).json()
    c = body["counters"]
    assert (c["requests"], c["exceptions"], c["holds_expiring"], c["escalations"], c["failed_messages"], c["eta_changes"]) == (3, 1, 1, 1, 1, 1)
    assert c["total"] == 8
    prios = [i["priority_code"] for i in body["items"]]
    order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    assert [order[p] for p in prios] == sorted(order[p] for p in prios)
    kinds = {i["kind"] for i in body["items"]}
    assert kinds == {"request", "exception", "hold", "escalation", "failed_message", "eta_change"}
    by_kind = {i["kind"]: i for i in body["items"] if i["kind"] != "request"}
    assert by_kind["hold"]["id"] == str(hold_id) and by_kind["hold"]["expires_at"] and "Expires in" in by_kind["hold"]["summary"]
    assert by_kind["exception"]["title"].endswith("Driver reported breakdown") and "Breakdown" in by_kind["exception"]["summary"]
    assert by_kind["escalation"]["summary"] == "nothing fits"
    # filters
    assert len((await client.get(f"{API}/inbox", params={"kind": "request"})).json()["items"]) == 3
    assert [i["shipment_code"] for i in (await client.get(f"{API}/inbox", params={"priority": "CRITICAL", "kind": "request"})).json()["items"]] == ["M4-CRIT"]
    assert (await client.get(f"{API}/inbox", params={"facility_id": str(world.facility_b.id)})).json()["items"] == []
    assert (await client.get(f"{API}/inbox", params={"kind": "bogus"})).status_code == 422
    await client.post(f"{API}/claim", json={"kind": "request", "id": str(r_crit)})
    mine = (await client.get(f"{API}/inbox", params={"claimed": "mine"})).json()["items"]
    assert [i["id"] for i in mine] == [str(r_crit)] and mine[0]["claimed_by"]["name"] == "Coordinator"
    assert len((await client.get(f"{API}/inbox", params={"claimed": "free"})).json()["items"]) == 7
    _ = r_low, r_exc


async def test_inbox_is_coordinator_only(client, world):
    for who in ("admin", "facility_planner", "carrier_user"):
        await as_coord(client, who)
        for path in ("/inbox", "/competing", "/escalations"):
            assert (await client.get(f"{API}{path}")).status_code == 403, (who, path)
        assert (await client.post(f"{API}/claim", json={"kind": "request", "id": str(uuid.uuid4())})).status_code == 403
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    assert (await client.get(f"{API}/inbox")).status_code == 401


# ---------------------------------------------------------------- request detail + recommendation
async def test_request_detail_with_feasible_hold_recommends_approve(client, world, m4):
    sh, rid, hold_id = await make_request(m4, world, "DET", exception=True, priority="HIGH")
    await orm_book(world.shipment_a.id, m4.slot("D2", "08:00").id, "CONFIRMED", code="CUR1") if False else None
    await as_coord(client)
    d = (await client.get(f"{API}/requests/{rid}")).json()
    assert d["request"]["status"] == "waiting" and d["shipment"]["code"] == "M4-DET" and d["facility"]["code"] == "FAC-A"
    assert d["shipment"]["driver_language"] == "en" and d["shipment"]["driver_phone"]
    assert d["facts"]["reason"] == "BREAKDOWN" and d["facts"]["reported_delay_min"] == 120
    assert "kharab" in d["facts"]["original_message"] and d["facts"]["requires_human_review"] is True and d["facts"]["translation"] is None
    assert d["held_option"]["feasible"] is True and d["held_option"]["slot_codes"] == [m4.slot("D1", "09:00").code]
    assert d["held_option"]["seconds_left"] > 0
    assert d["recommendation"]["action"] == "approve" and d["recommendation"]["source"] == "rules"
    assert "HIGH_PRIORITY" in d["recommendation"]["risk_flags"]
    assert d["options"] and d["options"][0]["rank"] == 1 and d["options"][0]["explanation"]
    assert d["eta"]["source"] == "ORIGINAL_PLAN" and d["eta_history"] == [] and d["current_appointment"] is None
    await client.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})
    assert (await client.get(f"{API}/requests/{rid}")).json()["claimed_by"]["name"] == "Coordinator"
    assert (await client.get(f"{API}/requests/{uuid.uuid4()}")).status_code == 404
    _ = hold_id


async def test_detail_expired_hold_recommends_suggest_and_replan_context(client, world, m4):
    sh, rid, hold_id = await make_request(m4, world, "EXP", reason_code="REPLAN_DOCK_EVENT")
    async with async_session_factory() as db:
        h = await db.get(SlotHold, hold_id)
        h.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    await orm_book(sh.id, m4.slot("D2", "08:00").id, "CONFIRMED", code="CURX")
    await as_coord(client)
    d = (await client.get(f"{API}/requests/{rid}")).json()
    assert d["held_option"]["feasible"] is False and d["held_option"]["seconds_left"] == 0
    assert d["recommendation"]["action"] == "suggest" and d["recommendation"]["slot_ids"]
    assert d["current_appointment"]["slot_code"] == m4.slot("D2", "08:00").code and d["current_appointment"]["status"] == "CONFIRMED"
    assert any("hold expired" in x.lower() for x in d["recommendation"]["reasons"])


async def test_detail_without_options_recommends_escalate(client, world, m4):
    sh = await new_shipment(world, "NOOPT", dock_type="HEAVY", weight=90000)  # no dock takes 90 t
    async with async_session_factory() as db:
        r = await engine.create_request(db, sh.id, reason_code="DRIVER_DELAY")
        await db.commit()
        rid = r.id
    await as_coord(client)
    d = (await client.get(f"{API}/requests/{rid}")).json()
    assert d["options"] == [] and d["recommendation"]["action"] == "escalate" and d["held_option"] is None


# ---------------------------------------------------------------- decisions + driver messages
async def test_approve_sends_template_to_driver_and_clears_lock(client, world, m4):
    sh, rid, _ = await make_request(m4, world, "APR")
    await as_coord(client)
    await client.post(f"{API}/claim", json={"kind": "request", "id": str(rid)})
    r = await client.post(f"/api/v1/booking/requests/{rid}/approve")
    assert r.status_code == 200 and r.json()["appointment_status"] == "CONFIRMED"
    ev = [e for e in await outbox("whatsapp.template") if e.payload["template"] == "appointment_confirmed"]
    assert len(ev) == 1 and ev[0].payload["variables"]["slot_code"] == m4.slot("D1", "09:00").code
    assert ev[0].payload["variables"]["dock_code"] == "D1" and "09:00" in ev[0].payload["variables"]["start"]
    assert ev[0].payload["language"] == "en" and ev[0].payload["deliverable"] is False  # unverified driver
    redis = get_redis()
    try:
        assert await redis.get(f"lock:request:{rid}") is None
    finally:
        await redis.aclose()


async def test_approval_after_last_start_uses_awaiting_template_and_replacement_uses_changed(client, world, m4):
    await __import__("tests.m4_helpers", fromlist=["add_rule"]).add_rule(world, "LAST_NEW_START_TIME", "20:00")
    sh, rid, _ = await make_request(m4, world, "LATE", slot=("D1", "21:00"))
    await as_coord(client)
    assert (await client.post(f"/api/v1/booking/requests/{rid}/approve")).json()["appointment_status"] == "PENDING_CONFIRMATION"
    assert [e.payload["template"] for e in await outbox("whatsapp.template")] == ["request_awaiting_approval"]
    sh2, rid2, _ = await make_request(m4, world, "SWAP", slot=("D2", "10:00"))
    await orm_book(sh2.id, m4.slot("D2", "08:00").id, "CONFIRMED", code="OLDSWAP")
    assert (await client.post(f"/api/v1/booking/requests/{rid2}/approve")).json()["replaced_appointment_id"]
    assert "appointment_changed" in [e.payload["template"] for e in await outbox("whatsapp.template")]


async def test_reject_and_suggest_message_the_driver(client, world, m4):
    sh, rid, _ = await make_request(m4, world, "REJ")
    await as_coord(client)
    assert (await client.post(f"/api/v1/booking/requests/{rid}/reject", json={"reason": "No capacity today"})).json()["status"] == "rejected"
    ev = (await outbox("whatsapp.template"))[-1]
    assert ev.payload["template"] == "appointment_changed" and ev.payload["variables"]["outcome"] == "not_possible"
    sh2, rid2, _ = await make_request(m4, world, "SUG", slot=("D1", "12:00"))
    s = await client.post(f"/api/v1/booking/requests/{rid2}/suggest", json={"slot_ids": m4.ids("D2", "13:00")})
    assert s.status_code == 200 and s.json()["status"] == "suggested"
    last = (await outbox("whatsapp.template"))[-1]
    assert last.payload["variables"]["offer"] is True and last.payload["variables"]["slot_code"] == m4.slot("D2", "13:00").code


# ---------------------------------------------------------------- escalate action
async def test_escalate_request_releases_hold_and_opens_escalation(client, world, m4):
    sh, rid, hold_id = await make_request(m4, world, "ESC", exception=True)
    await as_coord(client)
    r = await client.post(f"{API}/requests/{rid}/escalate", json={"reason": "Driver says truck is stuck, unclear ETA", "note": "call him"})
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["reason_code"] == "COORDINATOR_ESCALATION" and e["status"] == "open" and e["shipment_code"] == "M4-ESC"
    assert e["handoff_record"]["summary"].startswith("Driver says") and e["handoff_record"]["note"] == "call him"
    assert e["handoff_record"]["eta"]["source"] == "ORIGINAL_PLAN" and e["driver_phone"]
    async with async_session_factory() as db:
        assert (await db.get(ApprovalRequest, rid)).status == "escalated"
        assert (await db.get(SlotHold, hold_id)).status == "released"
    assert [x.payload["template"] for x in await outbox("whatsapp.template")] == ["escalation_notice"]
    assert (await client.post(f"{API}/requests/{rid}/escalate", json={"reason": "again please"})).status_code == 409
    assert (await client.post(f"{API}/requests/{uuid.uuid4()}/escalate", json={"reason": "no such"})).status_code == 404
    assert (await client.post(f"{API}/requests/{rid}/escalate", json={"reason": "x"})).status_code == 422
    # capacity freed: another shipment can take the released slot
    other = await new_shipment(world, "NEXT")
    await login(client, "coordinator")
    assert (await client.post("/api/v1/booking/holds", json={"shipment_id": str(other.id), "slot_ids": m4.ids("D1", "09:00")})).status_code == 201


async def test_escalate_blocked_by_other_coordinators_lock(client, world, m4):
    sh, rid, _ = await make_request(m4, world, "LCK")
    redis = get_redis()
    try:
        await redis.set(f"lock:request:{rid}", json.dumps({"id": str(uuid.uuid4()), "name": "Someone Else"}), ex=300)
    finally:
        await redis.aclose()
    await as_coord(client)
    r = await client.post(f"{API}/requests/{rid}/escalate", json={"reason": "stuck truck"})
    assert r.status_code == 409 and r.json()["error"]["details"]["claimed_by"]["name"] == "Someone Else"


# ---------------------------------------------------------------- competing requests
async def _competitors(m4_, world, specs):
    out = []
    for tag, prio, status in specs:
        sh = await new_shipment(world, tag, priority=prio, status=status)
        async with async_session_factory() as db:
            r = await engine.create_request(db, sh.id, reason_code="DRIVER_DELAY")
            await db.commit()
        out.append((sh, r.id))
    return out


async def test_competing_group_ranked_by_policy_and_override_needs_reason(client, world, m4):
    (low, r_low), (crit, r_crit) = await _competitors(m4, world, [("LOWX", "LOW", "ASSIGNED"), ("CRITX", "CRITICAL", "ASSIGNED")])
    await as_coord(client)
    g = (await client.get(f"{API}/competing")).json()["groups"]
    assert len(g) == 1 and g[0]["facility_code"] == "FAC-A"
    ranked = g[0]["requests"]
    assert [x["shipment_code"] for x in ranked] == ["M4-CRITX", "M4-LOWX"] and ranked[0]["rank"] == 1 and "CRITICAL priority" in ranked[0]["reasons"]
    assert (await client.get(f"{API}/competing", params={"facility_id": str(world.facility_b.id)})).json()["groups"] == []
    ids = [str(r_low), str(r_crit)]
    bad = await client.post(f"{API}/competing/decide", json={"winner_request_id": ids[0], "group_request_ids": ids})
    assert bad.status_code == 422 and "reason" in bad.json()["error"]["message"]
    short = await client.post(f"{API}/competing/decide", json={"winner_request_id": ids[0], "group_request_ids": ids, "override_reason": "too short"})
    assert short.status_code == 422
    outside = await client.post(f"{API}/competing/decide", json={"winner_request_id": str(uuid.uuid4()), "group_request_ids": ids})
    assert outside.status_code == 422
    ok = await client.post(f"{API}/competing/decide", json={"winner_request_id": ids[0], "group_request_ids": ids,
                                                           "override_reason": "Low priority load is perishable"})
    assert ok.status_code == 200 and ok.json()["overrode_policy"] is True and ok.json()["policy_winner_request_id"] == ids[1], ok.text
    async with async_session_factory() as db:
        won = await db.get(ApprovalRequest, uuid.UUID(ids[0]))
        assert won.status == "approved" and won.reason.startswith("OVERRIDE of ranking policy: Low priority")
        assert (await db.get(ApprovalRequest, uuid.UUID(ids[1]))).status == "waiting"


async def test_competing_policy_winner_needs_no_reason_and_fixed_truck_first(client, world, m4):
    (a, r_a), (b, r_b), (c, r_c) = await _competitors(m4, world, [("NRM", "NORMAL", "ASSIGNED"), ("UNLD", "LOW", "IN_DOCK"), ("HI", "HIGH", "ASSIGNED")])
    await as_coord(client)
    g = (await client.get(f"{API}/competing")).json()["groups"][0]["requests"]
    assert [x["shipment_code"] for x in g] == ["M4-UNLD", "M4-HI", "M4-NRM"] and g[0]["fixed"] is True
    ids = [str(r_a), str(r_b), str(r_c)]
    ok = await client.post(f"{API}/competing/decide", json={"winner_request_id": str(r_b), "group_request_ids": ids})
    assert ok.status_code == 200 and ok.json()["overrode_policy"] is False, ok.text
    ev = [e for e in await outbox("whatsapp.template") if e.payload["template"] == "appointment_confirmed"]
    assert len(ev) == 1
    again = await client.post(f"{API}/competing/decide", json={"winner_request_id": str(r_b), "group_request_ids": ids})
    assert again.status_code == 409 and again.json()["error"]["code"] == "REQUEST_CLOSED"


async def test_competing_tie_is_flagged(client, world, m4):
    await _competitors(m4, world, [("T1", "NORMAL", "ASSIGNED"), ("T2", "NORMAL", "ASSIGNED")])
    await as_coord(client)
    g = (await client.get(f"{API}/competing")).json()["groups"][0]["requests"]
    assert any(x["tie_with_next"] for x in g) or g[0]["score"] != g[1]["score"]  # waiting time can break an exact tie


# ---------------------------------------------------------------- holds extend
async def test_extend_hold_within_policy_then_limit(client, world, m4):
    sh = await new_shipment(world, "EXT")
    async with async_session_factory() as db:
        h = await engine.place_hold(db, sh.id, [m4.slot("D1", "09:00").id], ttl_minutes=10)
        await db.commit()
        hid, before = h.id, h.expires_at
    await as_coord(client)
    r = await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 20})
    assert r.status_code == 200
    async with async_session_factory() as db:
        assert (await db.get(SlotHold, hid)).expires_at == before + timedelta(minutes=20)
    assert (await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 60})).status_code == 200  # clamped to the 60 min cap
    over = await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 5})
    assert over.status_code == 409 and over.json()["error"]["code"] == "EXTENSION_LIMIT"
    assert (await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 0})).status_code == 422
    async with async_session_factory() as db:
        h = await db.get(SlotHold, hid)
        h.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert (await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 5})).json()["error"]["code"] == "HOLD_NOT_ACTIVE"
    await login(client, "facility_planner")
    assert (await client.post(f"/api/v1/booking/holds/{hid}/extend", json={"minutes": 5})).status_code == 403


# ---------------------------------------------------------------- escalations API
async def _esc(world, code="NO_FEASIBLE_SLOT", shipment=None):
    async with async_session_factory() as db:
        e = await engine.escalate(db, (shipment or world.shipment_a).id, code, {"summary": "No slot", "rejections": {"DOCK_EVENT": 4}})
        await db.commit()
        return e.id


async def test_escalation_lifecycle_and_filters(client, world, m4):
    e1, e2 = await _esc(world), await _esc(world, "SAFETY", world.shipment_b)
    await as_coord(client)
    lst = (await client.get(f"{API}/escalations")).json()
    assert {x["reason_code"] for x in lst} == {"NO_FEASIBLE_SLOT", "SAFETY"} and lst[0]["assigned_to"] is None
    assert [x["id"] for x in (await client.get(f"{API}/escalations", params={"status": "resolved"})).json()] == []
    one = (await client.get(f"{API}/escalations/{e1}")).json()
    assert one["shipment_code"] == "SHP-A" and one["handoff_record"]["rejections"]["DOCK_EVENT"] == 4 and one["driver_name"] == "Driver A"
    a = (await client.post(f"{API}/escalations/{e1}/assign", json={})).json()
    assert a["status"] == "in_progress" and a["assigned_to"]["name"] == "Coordinator"
    assert (await client.post(f"{API}/escalations/{e1}/status", json={"status": "resolved"})).status_code == 422
    assert (await client.post(f"{API}/escalations/{e2}/status", json={"status": "in_progress"})).json()["assigned_to"]["name"] == "Coordinator"
    assert (await client.post(f"{API}/escalations/{e1}/resolve", json={"resolution": "ok"})).status_code == 422
    done = (await client.post(f"{API}/escalations/{e1}/resolve", json={"resolution": "Rebooked manually after calling the driver"})).json()
    assert done["status"] == "resolved" and done["closed_at"] and done["resolution"].startswith("Rebooked")
    assert (await client.post(f"{API}/escalations/{e1}/resolve", json={"resolution": "second time"})).status_code == 409
    assert (await client.post(f"{API}/escalations/{e1}/assign", json={})).status_code == 409
    assert len((await client.get(f"{API}/escalations", params={"status": "resolved"})).json()) == 1
    assert (await client.get(f"{API}/escalations/{uuid.uuid4()}")).status_code == 404
    assert [x.payload["escalation_id"] for x in await outbox("escalation.resolved")] == [str(e1)]
    async with async_session_factory() as db:
        assert (await db.get(Escalation, e1)).status == "resolved"


async def test_inbox_exception_without_shipment_uses_normal_priority_scale(client, world):
    async with async_session_factory() as db:
        th = ChatThread(code="THNOSHIP", driver_id=world.shipment_a.driver_id, shipment_id=None, opened_at=NOW,
                        thread_status="OPEN", thread_intent="UNKNOWN")
        db.add(th)
        await db.flush()
        db.add(DriverException(code="EXNOSHIP", shipment_id=None, driver_id=world.shipment_a.driver_id, thread_id=th.id,
                               exception_type="UNKNOWN", reported_at=NOW, severity_code="MEDIUM", exception_status="OPEN",
                               description="Driver did not say which shipment"))
        await db.commit()
    await as_coord(client)
    item = (await client.get(f"{API}/inbox", params={"kind": "exception"})).json()["items"][0]
    assert item["priority_code"] == "NORMAL" and item["shipment_code"] is None
