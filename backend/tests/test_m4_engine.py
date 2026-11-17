"""Milestone 4: scheduling + booking engine, API level."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import async_session_factory
from app.core.errors import SlotTakenError, SlotUnavailableError
from app.modules.booking import engine
from app.modules.docks.models import DockStatusEvent
from app.modules.eta import service as eta_service
from app.modules.scheduling import service as scheduling_service
from app.modules.scheduling.ranking import RequestFacts, rank_requests
from tests.conftest import login
from tests.m4_helpers import (  # noqa: F401
    IST, DAY, add_rule, assert_invariants, at, m4, new_shipment, orm_book, rows, scalar,
)

API = "/api/v1"


def iso(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(s)


async def wide(sid, **kw) -> dict:
    """All feasible options (the API caps `limit` at 20), straight from the read-only scheduling service."""
    async with async_session_factory() as db:
        res = await scheduling_service.find_options(db, sid, limit=500, **kw)
        return {"options": [{"dock_code": o.dock_code, "slot_ids": [str(i) for i in o.slot_ids], "start": o.start, "end": o.end,
                             "reasons": o.reasons, "needs_planner_approval": o.needs_planner_approval,
                             "explanation": o.explanation} for o in res.options], "rejections": res.rejections}


async def as_role(client, who):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await login(client, who)


async def post_hold(c, sid, slots, **kw):
    return await c.post(f"{API}/booking/holds", json={"shipment_id": str(sid), "slot_ids": slots, **kw})


async def hold_req_approve(c, sid, slots):
    h = await post_hold(c, sid, slots)
    assert h.status_code == 201, h.text
    r = await c.post(f"{API}/booking/requests", json={"shipment_id": str(sid), "hold_id": h.json()["id"]})
    assert r.status_code == 201, r.text
    a = await c.post(f"{API}/booking/requests/{r.json()['id']}/approve")
    return h.json(), r.json(), a


async def options(c, sid, path="/scheduling/options", **kw):
    r = await c.post(f"{API}{path}", json={"shipment_id": str(sid), "limit": 20, **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def appt(code_or_id):
    return (await rows("SELECT appointment_status, is_current, replaced_appointment_id, cancellation_reason "
                       "FROM appointments WHERE id = :i", i=code_or_id))[0]


# ============================================================ options
async def test_options_ranked_with_reasons_and_never_reserve(client, world, m4):
    s = await new_shipment(world, "OPT")
    await as_role(client, "coordinator")
    for path in ("/scheduling/options", "/booking/options"):
        data = await options(client, s.id, path)
        opts = data["options"]
        assert [o["rank"] for o in opts] == list(range(1, len(opts) + 1)) and data["total_feasible"] > 5
        assert iso(opts[0]["start"]) == at("08:00") and opts[0]["dock_code"] == "D1"
        assert {"COMPATIBLE_DOCK", "FITS_UNLOAD_WINDOW", "AFTER_ETA"} <= set(opts[0]["reasons"])
        assert opts[0]["explanation"].startswith("Earliest compatible slot after the 07:00 ETA")
        assert opts[1]["explanation"].startswith("Starts ")
        assert data["eta"]["source"] == "ORIGINAL_PLAN" and data["eta"]["requires_human_review"] is False
    assert await scalar("SELECT count(*) FROM slot_holds") == 0
    assert await scalar("SELECT count(*) FROM slot_claims") == 0
    assert await scalar("SELECT count(*) FROM appointments") == 0


async def test_options_permissions_and_scope(client, world, m4):
    s = await new_shipment(world, "PERM")
    for who in ("carrier_user", "admin"):
        await as_role(client, who)
        for path in ("/scheduling/options", "/booking/options"):
            r = await client.post(f"{API}{path}", json={"shipment_id": str(s.id)})
            assert r.status_code == 403, (who, path)
    await as_role(client, "facility_planner")
    assert (await client.post(f"{API}/scheduling/options", json={"shipment_id": str(s.id)})).status_code == 200
    assert (await client.post(f"{API}/scheduling/options", json={"shipment_id": str(world.shipment_b.id)})).status_code == 404
    await as_role(client, "coordinator")
    other = await options(client, world.shipment_b.id)
    assert other["options"] == []  # facility B has no docks or slots


# ============================================================ hold -> approve
async def test_hold_approve_confirms_replaces_old_and_releases_slot(client, world, m4):
    s, t = await new_shipment(world, "S"), await new_shipment(world, "T")
    await as_role(client, "coordinator")
    h1, _, a1 = await hold_req_approve(client, s.id, m4.ids("D1", "08:00"))
    assert a1.status_code == 200 and a1.json()["appointment_status"] == "CONFIRMED" and a1.json()["is_current"]
    await assert_invariants()
    first = a1.json()["appointment_id"]
    _, _, a2 = await hold_req_approve(client, s.id, m4.ids("D1", "10:00"))
    assert a2.json()["replaced_appointment_id"] == first
    status, current, replaced_by, reason = await appt(first)
    assert status == "CANCELLED" and current is False and reason == "REPLACED"
    await assert_invariants()
    held = await post_hold(client, t.id, m4.ids("D1", "08:00"))  # the old slot is reusable
    assert held.status_code == 201
    assert (await post_hold(client, t.id, m4.ids("D1", "10:00"))).status_code == 409  # the new one is not
    await assert_invariants()


async def test_one_hold_at_a_time_and_idempotent_repeat(client, world, m4):
    s = await new_shipment(world, "ONE")
    await as_role(client, "coordinator")
    a = await post_hold(client, s.id, m4.ids("D1", "08:00"))
    again = await post_hold(client, s.id, m4.ids("D1", "08:00"))
    assert a.status_code == again.status_code == 201 and a.json()["id"] == again.json()["id"]
    b = await post_hold(client, s.id, m4.ids("D1", "09:00"))
    assert b.status_code == 201 and b.json()["id"] != a.json()["id"]
    assert (await rows("SELECT status FROM slot_holds WHERE id = :i", i=uuid.UUID(a.json()["id"])))[0][0] == "released"
    assert await scalar("SELECT count(*) FROM slot_holds WHERE status = 'active'") == 1
    await assert_invariants()


async def test_hold_validations(client, world, m4):
    s = await new_shipment(world, "VAL")
    await as_role(client, "coordinator")
    assert (await post_hold(client, s.id, m4.ids("D1", "08:00", "10:00"))).status_code == 409  # not consecutive
    assert (await post_hold(client, s.id, [str(uuid.uuid4())])).status_code == 404
    early = await post_hold(client, s.id, m4.ids("D1", "08:00", day_offset=0))
    assert early.status_code == 201
    other_dock = await post_hold(client, s.id, [m4.ids("D1", "08:00")[0], m4.ids("D2", "09:00")[0]])
    assert other_dock.status_code == 409 and other_dock.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    await assert_invariants()


# ============================================================ expiry
async def test_hold_expiry_sweep_notifies_and_reoffers(client, world, m4):
    s, t = await new_shipment(world, "EXP"), await new_shipment(world, "EXP2")
    slot = m4.slot("D1", "08:00").id
    t0 = datetime.now(UTC)
    async with async_session_factory() as db:
        hold = await engine.place_hold(db, s.id, [slot], now=t0)
        req = await engine.create_request(db, s.id, hold_id=hold.id)
        await db.commit()
        hold_id, req_id = hold.id, req.id
    await as_role(client, "coordinator")
    assert (await post_hold(client, t.id, [str(slot)])).status_code == 409  # still held
    async with async_session_factory() as db:
        assert (await engine.sweep(db, now=t0 + timedelta(minutes=5)))["holds_expired"] == 0
        counts = await engine.sweep(db, now=t0 + timedelta(minutes=16))
        await db.commit()
    assert counts["holds_expired"] == 1
    assert (await rows("SELECT status FROM slot_holds WHERE id = :i", i=hold_id))[0][0] == "expired"
    assert (await rows("SELECT status FROM approval_requests WHERE id = :i", i=req_id))[0][0] == "expired"
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'hold.expired'") == 1
    await assert_invariants()
    opts = await options(client, t.id)
    assert iso(opts["options"][0]["start"]) == at("08:00") and opts["options"][0]["dock_code"] == "D1"
    assert (await post_hold(client, t.id, [str(slot)])).status_code == 201
    async with async_session_factory() as db:  # sweeping twice is harmless
        assert (await engine.sweep(db, now=t0 + timedelta(minutes=1)))["holds_expired"] == 0


async def test_request_cannot_be_approved_after_sweep_expired_it(client, world, m4):
    s = await new_shipment(world, "SWEPT")
    t0 = datetime.now(UTC)
    async with async_session_factory() as db:
        hold = await engine.place_hold(db, s.id, m4.ids("D1", "08:00") and [m4.slot("D1", "08:00").id], now=t0 - timedelta(minutes=20))
        req = await engine.create_request(db, s.id, hold_id=hold.id)
        await engine.sweep(db, now=t0)
        await db.commit()
        req_id = req.id
    await as_role(client, "coordinator")
    r = await client.post(f"{API}/booking/requests/{req_id}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "REQUEST_CLOSED"


async def test_approve_after_expiry_only_if_slot_still_free(world, m4):
    s, t = await new_shipment(world, "LATE1"), await new_shipment(world, "LATE2")
    slot_a, slot_b = m4.slot("D1", "08:00").id, m4.slot("D1", "09:00").id
    t0 = datetime.now(UTC)
    async with async_session_factory() as db:  # both holds already expired but not yet swept
        ha = await engine.place_hold(db, s.id, [slot_a], now=t0 - timedelta(minutes=20))
        hb = await engine.place_hold(db, t.id, [slot_b], now=t0 - timedelta(minutes=20))
        await db.commit()
        ha_id, hb_id = ha.id, hb.id
    async with async_session_factory() as db:  # nobody took slot A: approval revives the hold
        a = await engine.approve_hold(db, ha_id, now=t0)
        await db.commit()
        assert a.appointment_status == "CONFIRMED"
    async with async_session_factory() as db:  # another shipment grabs slot B first
        u = await new_shipment(world, "LATE3")
        await engine.place_hold(db, u.id, [slot_b], now=t0)
        await db.commit()
    async with async_session_factory() as db:
        with pytest.raises(SlotTakenError):
            await engine.approve_hold(db, hb_id, now=t0)
        await db.rollback()
    await assert_invariants()


# ============================================================ suggest / hold / reject
async def test_suggest_keep_reject_and_double_approve(client, world, m4):
    s = await new_shipment(world, "SUG")
    await as_role(client, "coordinator")
    h = (await post_hold(client, s.id, m4.ids("D1", "08:00"))).json()
    req = (await client.post(f"{API}/booking/requests", json={"shipment_id": str(s.id), "hold_id": h["id"]})).json()
    assert req["status"] == "waiting"
    sug = await client.post(f"{API}/booking/requests/{req['id']}/suggest", json={"slot_ids": m4.ids("D2", "09:00")})
    assert sug.status_code == 200 and sug.json()["status"] == "suggested" and sug.json()["hold_id"] != h["id"]
    assert (await rows("SELECT status FROM slot_holds WHERE id = :i", i=uuid.UUID(h["id"])))[0][0] == "released"
    assert await scalar("SELECT count(*) FROM slot_holds WHERE status = 'active'") == 1
    await assert_invariants()
    kept = await client.post(f"{API}/booking/requests/{req['id']}/hold", json={"extend_minutes": 60})
    assert kept.status_code == 200 and kept.json()["status"] == "held"
    exp, created = (await rows("SELECT expires_at, created_at FROM slot_holds WHERE status = 'active'"))[0]
    assert exp > datetime.now(UTC) + timedelta(minutes=14)
    assert exp <= created + timedelta(minutes=60, seconds=1)  # never beyond max_hold_minutes
    rej = await client.post(f"{API}/booking/requests/{req['id']}/reject", json={"reason": "driver declined"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert await scalar("SELECT count(*) FROM slot_holds WHERE status = 'active'") == 0
    assert (await client.post(f"{API}/booking/requests/{req['id']}/approve")).status_code == 409
    assert (await client.post(f"{API}/booking/requests/{req['id']}/reject", json={"reason": "again"})).status_code == 409
    await assert_invariants()


async def test_approve_twice_is_idempotent(world, m4):
    s = await new_shipment(world, "TWICE")
    async with async_session_factory() as db:
        hold = await engine.place_hold(db, s.id, [m4.slot("D1", "08:00").id])
        a1 = await engine.approve_hold(db, hold.id)
        await db.commit()
        hold_id, a1_id = hold.id, a1.id
    async with async_session_factory() as db:
        a2 = await engine.approve_hold(db, hold_id)
        await db.commit()
    assert a2.id == a1_id
    assert await scalar("SELECT count(*) FROM appointments") == 1
    await assert_invariants()


# ============================================================ starts after 21:00
async def test_late_start_pending_confirmation_flow(client, world, m4):
    await add_rule(world, "LAST_NEW_START_TIME", "20:00")
    s = await new_shipment(world, "LATE")
    await as_role(client, "coordinator")
    opts = (await wide(s.id, effective_eta=at("20:30")))["options"]
    flags = [o["needs_planner_approval"] for o in opts]
    assert any(flags) and not all(flags)
    assert flags == sorted(flags), "approval-free options must rank before options needing planner approval"
    assert "NEEDS_PLANNER_APPROVAL" in next(o for o in opts if o["needs_planner_approval"])["reasons"]
    base = await client.post(f"{API}/booking/book", json={"shipment_id": str(s.id), "slot_ids": m4.ids("D1", "08:00")})
    assert base.status_code == 201 and base.json()["appointment_status"] == "CONFIRMED"
    old = base.json()["appointment_id"]
    _, _, a = await hold_req_approve(client, s.id, m4.ids("D1", "21:00"))
    assert a.status_code == 200 and a.json()["appointment_status"] == "PENDING_CONFIRMATION"
    assert a.json()["is_current"] is False and a.json()["replaced_appointment_id"] == old
    pending = a.json()["appointment_id"]
    assert (await appt(old))[0] == "CONFIRMED" and (await appt(old))[1] is True
    await assert_invariants()
    # the planner confirms: the old booking is replaced and its slot freed
    await as_role(client, "facility_planner")
    pend = (await client.get(f"{API}/appointments/pending", params={"facility_id": str(world.facility_a.id)})).json()
    assert [p["reason"] for p in pend] == ["STARTS_AFTER_LAST_START"]
    ok = await client.post(f"{API}/appointments/{pending}/confirm")
    assert ok.status_code == 200 and ok.json()["appointment_status"] == "CONFIRMED" and ok.json()["is_current"]
    assert (await appt(old))[0] == "CANCELLED" and (await appt(old))[3] == "REPLACED"
    await assert_invariants()
    assert (await client.post(f"{API}/appointments/{pending}/confirm")).status_code == 409


async def test_late_start_reject_keeps_old_and_expiry_sweep_cancels_pending(client, world, m4):
    await add_rule(world, "LAST_NEW_START_TIME", "20:00")
    s, t = await new_shipment(world, "REJ"), await new_shipment(world, "EXPIRE")
    await as_role(client, "coordinator")
    olds, pendings = {}, {}
    for sh, early, late in ((s, "08:00", "21:00"), (t, "09:00", "21:00")):
        base = await client.post(f"{API}/booking/book", json={"shipment_id": str(sh.id), "slot_ids": m4.ids("D1", early)})
        olds[sh.id] = base.json()["appointment_id"]
        slot = m4.ids("D1" if sh is s else "D2", late)
        _, _, a = await hold_req_approve(client, sh.id, slot)
        assert a.json()["appointment_status"] == "PENDING_CONFIRMATION", a.text
        pendings[sh.id] = a.json()["appointment_id"]
    await as_role(client, "facility_planner")
    rej = await client.post(f"{API}/appointments/{pendings[s.id]}/reject", json={"reason": "no night crew"})
    assert rej.status_code == 200 and rej.json()["appointment_status"] == "REJECTED"
    assert (await appt(olds[s.id]))[:2] == ("CONFIRMED", True)  # the driver keeps the original booking
    await assert_invariants()
    t0 = datetime.now(UTC)
    async with async_session_factory() as db:
        counts = await engine.sweep(db, now=t0 + timedelta(minutes=31))
        await db.commit()
    assert counts["pending_expired"] == 1
    st, cur, _, reason = await appt(pendings[t.id])
    assert st == "CANCELLED" and cur is False and reason == "PENDING_EXPIRED"
    assert (await appt(olds[t.id]))[:2] == ("CONFIRMED", True)
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'pending.expired'") == 1
    await assert_invariants()


# ============================================================ multi-window
async def test_multi_window_option_claims_both_slots(client, world, m4):
    s, t = await new_shipment(world, "LONG", unload=100), await new_shipment(world, "SHORT")
    await as_role(client, "coordinator")
    opts = (await wide(s.id))["options"]
    d1 = next(o for o in opts if o["dock_code"] == "D1")
    assert len(d1["slot_ids"]) == 2 and "COMBINES_2_WINDOWS" in d1["reasons"] and "20 min" in d1["explanation"]
    assert iso(d1["end"]) - iso(d1["start"]) == timedelta(minutes=120)
    h, _, a = await hold_req_approve(client, s.id, d1["slot_ids"])
    assert a.status_code == 200 and a.json()["appointment_status"] == "CONFIRMED"
    assert await scalar("SELECT count(*) FROM slot_claims WHERE active AND appointment_id IS NOT NULL") == 2
    for hm in ("08:00", "09:00"):
        r = await post_hold(client, t.id, m4.ids("D1", hm))
        assert r.status_code == 409 and r.json()["error"]["code"] == "SLOT_TAKEN"
    assert (await post_hold(client, t.id, m4.ids("D1", "10:00"))).status_code == 201
    await assert_invariants()


async def test_heavy_dock_uses_90_minute_windows(client, world, m4):
    s = await new_shipment(world, "HEAVY", dock_type="HEAVY", weight=30000)
    await as_role(client, "coordinator")
    opts = (await wide(s.id))["options"]
    assert {o["dock_code"] for o in opts} == {"H1"}
    assert iso(opts[0]["end"]) - iso(opts[0]["start"]) == timedelta(minutes=90) and "30 min" in opts[0]["explanation"]


# ============================================================ compatibility
async def test_reefer_load_only_on_reefer_dock(client, world, m4):
    s = await new_shipment(world, "COLD", dock_type="REEFER", temp=True)
    await as_role(client, "coordinator")
    data = await wide(s.id)
    assert {o["dock_code"] for o in data["options"]} == {"R1"}
    assert data["rejections"].get("NEEDS_REEFER_DOCK", 0) > 0
    r = await post_hold(client, s.id, m4.ids("D1", "08:00"))
    assert r.status_code == 409 and "NEEDS_REEFER_DOCK" in r.json()["error"]["details"]["reasons"]


async def test_heavy_rule_and_weight_limits(client, world, m4):
    await add_rule(world, "HEAVY_DOCK_REQUIRED_KG", "25000")
    big, mid, huge = (await new_shipment(world, "BIG", weight=26000), await new_shipment(world, "MID", weight=24000),
                      await new_shipment(world, "HUGE", weight=45000))
    await as_role(client, "coordinator")
    assert {o["dock_code"] for o in (await wide(big.id))["options"]} == {"H1"}
    assert {"D1", "D2"} <= {o["dock_code"] for o in (await wide(mid.id))["options"]}
    d = await wide(huge.id)
    assert {o["dock_code"] for o in d["options"]} == {"H1"} and d["rejections"]["LOAD_EXCEEDS_DOCK_LIMIT"] > 0


async def test_vehicle_type_restriction_on_dock(client, world, m4):
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("UPDATE docks SET compatible_vehicle_type_codes = '[\"VT2\"]' WHERE dock_code = 'D2'"))
        await db.commit()
    s1, s2 = await new_shipment(world, "V1"), await new_shipment(world, "V2", vehicle_type_code="VT2")
    await as_role(client, "coordinator")
    d1 = await wide(s1.id)
    assert "D2" not in {o["dock_code"] for o in d1["options"]} and d1["rejections"]["VEHICLE_TYPE_NOT_ALLOWED"] > 0
    assert "D2" in {o["dock_code"] for o in (await wide(s2.id))["options"]}
    r = await post_hold(client, s1.id, m4.ids("D2", "08:00"))
    assert r.status_code == 409 and "VEHICLE_TYPE_NOT_ALLOWED" in r.json()["error"]["details"]["reasons"]


async def test_reefer_dock_down_means_no_option_and_escalation(client, world, m4):
    async with async_session_factory() as db:
        db.add(DockStatusEvent(dock_id=m4.docks["R1"].id, event_type="BREAKDOWN", event_start_ts=at("00:00", -1),
                               event_end_ts=None, reason="compressor failure"))
        await db.commit()
    s = await new_shipment(world, "NOCOLD", dock_type="REEFER", temp=True)
    await as_role(client, "coordinator")
    plain = await options(client, s.id, "/booking/options")
    assert plain["options"] == [] and plain["escalation_id"] is None
    assert await scalar("SELECT count(*) FROM escalations") == 0  # asking never escalates by itself
    data = await options(client, s.id, "/booking/options", escalate_if_none=True)
    assert data["options"] == [] and data["escalation_id"] and "escalated" in data["note"]
    reason, record, status = (await rows("SELECT reason_code, handoff_record, status FROM escalations"))[0]
    assert (reason, status) == ("NO_FEASIBLE_SLOT", "open")
    assert record["rejections"]["DOCK_EVENT"] > 0 and record["shipment"]["code"] == s.code
    assert record["eta"]["source"] == "ORIGINAL_PLAN" and "No compatible" in record["summary"]
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'escalation.created'") == 1


# ============================================================ dock breakdown after confirmation
async def test_breakdown_invalidates_bookings_and_holds(client, world, m4):
    s, t = await new_shipment(world, "BRK"), await new_shipment(world, "BRK2")
    await as_role(client, "coordinator")
    _, _, a = await hold_req_approve(client, s.id, m4.ids("D1", "09:00"))
    appt_id = a.json()["appointment_id"]
    h = (await post_hold(client, t.id, m4.ids("D1", "10:00"))).json()
    req = (await client.post(f"{API}/booking/requests", json={"shipment_id": str(t.id), "hold_id": h["id"]})).json()
    await as_role(client, "facility_planner")
    ev = await client.post(f"{API}/dock-events", json={
        "dock_id": str(m4.docks["D1"].id), "event_type": "BREAKDOWN", "event_start_ts": at("08:30").isoformat(),
        "event_end_ts": at("13:00").isoformat(), "reason": "hydraulic failure"})
    assert ev.status_code == 201 and [x["appointment_id"] for x in ev.json()["affected_appointments"]] == [appt_id]
    replans = await rows("SELECT shipment_id, status, reason_code FROM approval_requests WHERE reason_code = 'REPLAN_DOCK_EVENT'")
    assert replans == [(s.id, "waiting", "REPLAN_DOCK_EVENT")]
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'replan.requested'") == 1
    await as_role(client, "coordinator")
    bad = await client.post(f"{API}/booking/requests/{req['id']}/approve")
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert "DOCK_EVENT" in bad.json()["error"]["details"]["reasons"]
    assert (await post_hold(client, t.id, m4.ids("D1", "11:00"))).status_code == 409
    assert (await post_hold(client, t.id, m4.ids("D1", "14:00"))).status_code == 201  # after the outage
    await assert_invariants()


# ============================================================ ETA
async def test_eta_latest_wins_and_history_kept(client, world, m4):
    s = await new_shipment(world, "ETA1")
    async with async_session_factory() as db:
        for src, hm in (("DRIVER_DECLARED", "09:00"), ("WAREHOUSE_ESTIMATE", "10:00"), ("OPERATIONS_OVERRIDE", "11:00")):
            await eta_service.record_update(db, s.id, source_type=src, declared_eta_ts=at(hm), confidence="HIGH")
        await db.commit()
        assert len(await eta_service.history(db, s.id)) == 3
    await as_role(client, "coordinator")
    data = await options(client, s.id)
    assert iso(data["eta"]["ts"]) == at("11:00") and data["eta"]["source"] == "OPERATIONS_OVERRIDE"
    assert all(iso(o["start"]) >= at("11:00") for o in data["options"]) and iso(data["options"][0]["start"]) == at("11:00")


async def test_eta_range_uses_upper_bound_and_flags_review(client, world, m4):
    s = await new_shipment(world, "ETA2")
    async with async_session_factory() as db:
        await eta_service.record_update(db, s.id, source_type="DRIVER_DECLARED", declared_eta_ts=at("10:00"),
                                        upper_ts=at("12:00"), confidence="MEDIUM")
        await db.commit()
    await as_role(client, "coordinator")
    data = await options(client, s.id)
    assert iso(data["eta"]["ts"]) == at("12:00") and iso(data["eta"]["upper_ts"]) == at("12:00")
    assert data["eta"]["requires_human_review"] is True and iso(data["options"][0]["start"]) == at("12:00")


async def test_eta_vague_is_flagged(client, world, m4):
    s = await new_shipment(world, "ETA3")
    async with async_session_factory() as db:
        await eta_service.record_update(db, s.id, source_type="DRIVER_DECLARED", declared_eta_ts=at("09:00"), confidence="LOW")
        await db.commit()
    await as_role(client, "coordinator")
    assert (await options(client, s.id))["eta"]["requires_human_review"] is True


async def test_early_and_late_arrival(client, world, m4):
    early, late = await new_shipment(world, "EARLY", eta=at("03:00")), await new_shipment(world, "LATER", eta=at("15:30"))
    await as_role(client, "coordinator")
    e = (await options(client, early.id))["options"]
    assert iso(e[0]["start"]) == at("08:00")  # the earliest slot, never before opening
    l = (await options(client, late.id))["options"]
    assert all(iso(o["start"]) >= at("15:30") for o in l) and iso(l[0]["start"]) == at("15:30")
    r = await post_hold(client, late.id, m4.ids("D1", "08:00"))  # a slot before the ETA is refused at hold time
    assert r.status_code == 409 and "BEFORE_ETA" in r.json()["error"]["details"]["reasons"]


async def test_latest_finish_constraint(client, world, m4):
    s = await new_shipment(world, "FIN")
    await as_role(client, "coordinator")
    data = await options(client, s.id, latest_finish=at("10:00").isoformat())
    assert data["options"] and all(iso(o["start"]) + timedelta(minutes=60) <= at("10:00") for o in data["options"])
    assert "MEETS_FINISH_DEADLINE" in data["options"][0]["reasons"]
    none = await options(client, s.id, latest_finish=at("07:30").isoformat())
    assert none["options"] == [] and none["rejections"]["MISSES_DEADLINE"] > 0


# ============================================================ cancel / no-show / yard
async def test_cancel_frees_capacity(client, world, m4):
    s, t = await new_shipment(world, "CAN"), await new_shipment(world, "CAN2")
    await as_role(client, "facility_planner")
    b = await client.post(f"{API}/booking/book", json={"shipment_id": str(s.id), "slot_ids": m4.ids("D1", "08:00")})
    assert b.status_code == 201
    await as_role(client, "coordinator")
    assert (await post_hold(client, t.id, m4.ids("D1", "08:00"))).status_code == 409
    await as_role(client, "facility_planner")
    c = await client.post(f"{API}/booking/appointments/{b.json()['appointment_id']}/cancel", json={"reason": "customer cancelled"})
    assert c.status_code == 200 and c.json()["appointment_status"] == "CANCELLED"
    await assert_invariants()
    await as_role(client, "coordinator")
    assert (await post_hold(client, t.id, m4.ids("D1", "08:00"))).status_code == 201
    await assert_invariants()


async def test_cancelled_shipment_cannot_hold(client, world, m4):
    s = await new_shipment(world, "DEAD", status="CANCELLED")
    await as_role(client, "coordinator")
    r = await post_hold(client, s.id, m4.ids("D1", "08:00"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SHIPMENT_CLOSED"


async def test_yard_in_progress_is_fixed_overrun_and_completion_release_claims(client, world, m4):
    s = await new_shipment(world, "YARD")
    await as_role(client, "facility_planner")
    b = (await client.post(f"{API}/booking/book", json={"shipment_id": str(s.id), "slot_ids": m4.ids("D1", "08:00")})).json()
    ci = await client.post(f"{API}/yard/check-in", json={"shipment_id": str(s.id)})
    assert ci.status_code == 201
    cid = ci.json()["checkin_id"]
    assert (await client.post(f"{API}/yard/{cid}/assign-dock", json={"dock_id": str(m4.docks["D1"].id)})).status_code == 200
    assert (await client.post(f"{API}/yard/{cid}/start-unload")).status_code == 200
    assert (await appt(b["appointment_id"]))[0] == "IN_PROGRESS"
    c = await client.post(f"{API}/booking/appointments/{b['appointment_id']}/cancel", json={"reason": "cancel now"})
    assert c.status_code == 409 and c.json()["error"]["code"] == "FIXED_IN_PROGRESS"
    mv = await client.post(f"{API}/booking/appointments/{b['appointment_id']}/move", json={"slot_ids": m4.ids("D2", "10:00")})
    assert mv.status_code == 409 and mv.json()["error"]["code"] == "FIXED_IN_PROGRESS"
    await assert_invariants()  # an unloading truck still owns its claim
    assert await scalar("SELECT count(*) FROM slot_claims WHERE active AND appointment_id IS NOT NULL") == 1
    from sqlalchemy import text

    async with async_session_factory() as db:
        await db.execute(text("UPDATE facility_checkins SET unload_start_ts = now() - interval '90 minutes', "
                              "gate_in_ts = now() - interval '120 minutes'"))
        await db.commit()
    fin = await client.post(f"{API}/yard/{cid}/finish-unload")
    assert fin.status_code == 200 and fin.json()["overrun_min"] == 30 and fin.json()["unload_min"] == 90
    assert fin.json()["detention_min"] == 30
    assert (await appt(b["appointment_id"]))[0] == "COMPLETED"
    assert await scalar("SELECT count(*) FROM slot_claims WHERE active") == 0
    await assert_invariants()


async def test_no_show_after_grace_frees_claims(client, world, m4):
    from sqlalchemy import text

    from tests.m4_helpers import _mk_slot

    s, t = await new_shipment(world, "NS"), await new_shipment(world, "NS2")
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    start = datetime.combine(yesterday, datetime.min.time().replace(hour=10), tzinfo=IST).astimezone(UTC)
    async with async_session_factory() as db:
        slot = await _mk_slot(db, world.facility_a, await db.get(__import__("app.modules.docks.models", fromlist=["Dock"]).Dock, m4.docks["D1"].id),
                              start, start + timedelta(hours=1))
        await db.flush()
        slot_id = slot.id
        await db.commit()
    appt_id = await orm_book(s.id, slot_id, "CONFIRMED")
    await assert_invariants()
    await as_role(client, "facility_planner")
    r = await client.post(f"{API}/yard/no-show", json={"appointment_id": str(appt_id)})
    assert r.status_code == 200 and r.json()["appointment_status"] == "NO_SHOW"
    assert await scalar("SELECT count(*) FROM slot_claims WHERE active") == 0
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'appointment.no_show'") == 1
    await assert_invariants()
    async with async_session_factory() as db:  # the slot is free again for the engine
        hold = await engine.place_hold(db, t.id, [slot_id], now=start - timedelta(hours=2), check_eta=False)
        await db.commit()
        assert hold.status == "active"
    assert text is not None


# ============================================================ planner move
async def test_planner_move_validate_and_swap(client, world, m4):
    s, t = await new_shipment(world, "MV"), await new_shipment(world, "MV2")
    await as_role(client, "facility_planner")
    a = (await client.post(f"{API}/booking/book", json={"shipment_id": str(s.id), "slot_ids": m4.ids("D1", "08:00")})).json()
    blocker = await client.post(f"{API}/booking/book", json={"shipment_id": str(t.id), "slot_ids": m4.ids("D2", "10:00")})
    assert blocker.status_code == 201
    ok = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/validate-move", json={"slot_ids": m4.ids("D2", "09:00")})
    assert ok.json() == {"feasible": True, "problems": [], "needs_planner_approval": False}
    taken = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/validate-move", json={"slot_ids": m4.ids("D2", "10:00")})
    assert taken.json()["feasible"] is False and "OCCUPIED" in taken.json()["problems"]
    assert (await client.post(f"{API}/booking/appointments/{a['appointment_id']}/move", json={"slot_ids": m4.ids("D2", "10:00")})).status_code == 409
    moved = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/move", json={"slot_ids": m4.ids("D2", "09:00")})
    assert moved.status_code == 200 and moved.json()["appointment_status"] == "CONFIRMED"
    assert moved.json()["replaced_appointment_id"] == a["appointment_id"]
    assert (await appt(a["appointment_id"]))[0] == "CANCELLED"
    await assert_invariants()
    await as_role(client, "coordinator")
    u = await new_shipment(world, "MV3")
    assert (await post_hold(client, u.id, m4.ids("D1", "08:00"))).status_code == 201  # the vacated slot is free


async def test_planner_move_before_eta_is_infeasible_and_late_move_becomes_pending(client, world, m4):
    await add_rule(world, "LAST_NEW_START_TIME", "20:00")
    s = await new_shipment(world, "MV4", eta=at("12:00"))
    await as_role(client, "facility_planner")
    a = (await client.post(f"{API}/booking/book", json={"shipment_id": str(s.id), "slot_ids": m4.ids("D1", "13:00")})).json()
    early = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/validate-move", json={"slot_ids": m4.ids("D2", "09:00")})
    assert early.json()["feasible"] is False and early.json()["problems"] == ["BEFORE_ETA"]
    late = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/validate-move", json={"slot_ids": m4.ids("D1", "21:00")})
    assert late.json() == {"feasible": True, "problems": [], "needs_planner_approval": True}
    mv = await client.post(f"{API}/booking/appointments/{a['appointment_id']}/move", json={"slot_ids": m4.ids("D1", "21:00")})
    assert mv.status_code == 200 and mv.json()["appointment_status"] == "PENDING_CONFIRMATION" and mv.json()["needs_planner_approval"]
    assert (await appt(a["appointment_id"]))[:2] == ("CONFIRMED", True)
    await assert_invariants()


# ============================================================ ranking policy
def test_rank_requests_policy_order_and_ties():
    now = at("06:00")
    start = at("09:00")
    reqs = [RequestFacts(id="low", priority_code="LOW", option_start=start), RequestFacts(id="crit", priority_code="CRITICAL", option_start=start),
            RequestFacts(id="norm", priority_code="NORMAL", option_start=start), RequestFacts(id="high", priority_code="HIGH", option_start=start)]
    assert [r.id for r in rank_requests(reqs, now=now)] == ["crit", "high", "norm", "low"]
    fixed = rank_requests(reqs + [RequestFacts(id="busy", priority_code="LOW", option_start=start, is_unloading=True)], now=now)
    assert fixed[0].id == "busy" and fixed[0].fixed and "Already unloading" in fixed[0].reasons[0]
    lost = rank_requests([RequestFacts(id="a", priority_code="NORMAL", option_start=start),
                          RequestFacts(id="b", priority_code="NORMAL", option_start=start, lost_appointment=True)], now=now)
    assert [r.id for r in lost] == ["b", "a"]
    wait = rank_requests([RequestFacts(id="a", priority_code="NORMAL", option_start=start),
                          RequestFacts(id="b", priority_code="NORMAL", option_start=start, waiting_min=120)], now=now)
    assert [r.id for r in wait] == ["b", "a"]
    tie = rank_requests([RequestFacts(id="x", priority_code="NORMAL", option_start=start),
                         RequestFacts(id="y", priority_code="NORMAL", option_start=start)], now=now)
    assert tie[0].tie_with_next is True and "human decision" in tie[0].reasons[-1] and tie[1].tie_with_next is False


async def test_delayed_trucks_chasing_nearby_slots_get_distinct_capacity_by_priority(client, world, m4):
    eta = at("08:30")
    trucks = {p: await new_shipment(world, f"CH-{p}", priority=p, eta=eta) for p in ("LOW", "CRITICAL", "NORMAL", "HIGH")}
    ranked = rank_requests([RequestFacts(id=p, priority_code=p, option_start=at("09:00")) for p in trucks], now=at("06:00"))
    order = [r.id for r in ranked]
    assert order == ["CRITICAL", "HIGH", "NORMAL", "LOW"]
    await as_role(client, "coordinator")
    got = {}
    for p in order:
        o = (await options(client, trucks[p].id, "/booking/options", limit=1))["options"][0]
        _, _, a = await hold_req_approve(client, trucks[p].id, o["slot_ids"])
        assert a.status_code == 200 and a.json()["appointment_status"] == "CONFIRMED"
        got[p] = (tuple(o["slot_ids"]), iso(o["start"]))
    assert len({v[0] for v in got.values()}) == 4, "two trucks were promised the same slot"
    assert all(v[1] >= eta for v in got.values())
    assert got["CRITICAL"][1] <= min(v[1] for v in got.values())
    await assert_invariants()


# ============================================================ permissions
async def test_role_permissions_on_booking_endpoints(client, world, m4):
    s = await new_shipment(world, "ROLE")
    rid, slots = str(uuid.uuid4()), m4.ids("D1", "08:00")
    calls = [("post", "/booking/holds", {"shipment_id": str(s.id), "slot_ids": slots}), ("get", "/booking/holds", None),
             ("post", "/booking/requests", {"shipment_id": str(s.id)}), ("get", "/booking/requests", None),
             ("post", f"/booking/requests/{rid}/approve", None), ("post", f"/booking/requests/{rid}/suggest", {"slot_ids": slots}),
             ("post", f"/booking/requests/{rid}/hold", {}), ("post", f"/booking/requests/{rid}/reject", {"reason": "nope"}),
             ("post", f"/booking/holds/{rid}/release", None),
             ("post", "/booking/book", {"shipment_id": str(s.id), "slot_ids": slots}),
             ("post", f"/booking/appointments/{rid}/validate-move", {"slot_ids": slots}),
             ("post", f"/booking/appointments/{rid}/move", {"slot_ids": slots}),
             ("post", f"/booking/appointments/{rid}/cancel", {"reason": "nope"}),
             ("post", "/booking/options", {"shipment_id": str(s.id)}), ("post", "/scheduling/options", {"shipment_id": str(s.id)})]

    async def status(method, path, body):
        r = await (client.get(API + path) if method == "get" else client.post(API + path, json=body))
        return r.status_code

    await as_role(client, "carrier_user")
    assert {await status(*c) for c in calls} == {403}, "carrier users may never touch /booking or /scheduling"
    await as_role(client, "admin")
    assert {await status(*c) for c in calls} == {403}, "admin has no booking_decisions or day_schedule W"
    await as_role(client, "facility_planner")  # booking_decisions R, day_schedule W
    allowed = {"/booking/book", "/booking/options", "/scheduling/options", "/booking/holds_get"}
    for method, path, body in calls:
        code = await status(method, path, body)
        if path in allowed or (method == "get") or "/appointments/" in path:
            assert code != 403, (path, code)
        else:
            assert code == 403, (path, code)
    await as_role(client, "coordinator")
    t = await new_shipment(world, "ROLE2")
    assert (await post_hold(client, t.id, m4.ids("D2", "09:00"))).status_code == 201


# ============================================================ outbox
async def test_outbox_rows_are_written_in_the_same_transaction(client, world, m4):
    s = await new_shipment(world, "OUT")
    await as_role(client, "coordinator")
    h, req, a = await hold_req_approve(client, s.id, m4.ids("D1", "08:00"))
    types = [r[0] for r in await rows("SELECT event_type FROM outbox_events ORDER BY created_at")]
    assert types[:2] == ["hold.placed", "request.created"] and "appointment.confirmed" in types
    payload = (await rows("SELECT payload FROM outbox_events WHERE event_type = 'appointment.confirmed'"))[0][0]
    assert payload["shipment_id"] == str(s.id) and payload["appointment_id"] == a.json()["appointment_id"]
    await as_role(client, "facility_planner")
    await client.post(f"{API}/booking/appointments/{a.json()['appointment_id']}/cancel", json={"reason": "cancel it"})
    assert await scalar("SELECT count(*) FROM outbox_events WHERE event_type = 'appointment.cancelled'") == 1


async def test_rollback_leaves_no_state_and_no_outbox(world, m4):
    s = await new_shipment(world, "RB")
    async with async_session_factory() as db:
        hold = await engine.place_hold(db, s.id, [m4.slot("D1", "08:00").id])
        await engine.approve_hold(db, hold.id)
        await db.flush()
        from sqlalchemy import text

        assert (await db.execute(text("SELECT count(*) FROM outbox_events"))).scalar_one() == 2  # visible in-transaction
        await db.rollback()
    for table in ("outbox_events", "slot_holds", "slot_claims", "appointments"):
        assert await scalar(f"SELECT count(*) FROM {table}") == 0, table
    # a failed approval (breakdown) must not leave an outbox row either
    async with async_session_factory() as db:
        hold = await engine.place_hold(db, s.id, [m4.slot("D2", "08:00").id])
        await db.commit()
        hid = hold.id
    async with async_session_factory() as db:
        db.add(DockStatusEvent(dock_id=m4.docks["D2"].id, event_type="BREAKDOWN", event_start_ts=at("00:00"), event_end_ts=at("23:00"),
                               reason="pump failure"))
        await db.commit()
    before = await scalar("SELECT count(*) FROM outbox_events")
    async with async_session_factory() as db:
        with pytest.raises(SlotUnavailableError):
            await engine.approve_hold(db, hid)
        await db.rollback()
    assert await scalar("SELECT count(*) FROM outbox_events") == before
