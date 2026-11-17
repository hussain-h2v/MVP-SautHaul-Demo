"""Milestone 4 integrity proof as tests: real concurrency through the real API and PostgreSQL.

Every request below goes through the FastAPI app (ASGITransport) with its own client and its own database
connection (the test engine uses NullPool), so the races are real races inside PostgreSQL, not mocks."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import async_session_factory
from app.modules.booking import engine
from tests.conftest import login
from tests.m4_helpers import (  # noqa: F401
    assert_invariants, at, clone_clients, close_all, m4, new_shipment, rows, scalar,
)

API = "/api/v1"


async def coordinator(client, n):
    await login(client, "coordinator")
    return await clone_clients(client, n)


async def shipments(world, tag, n, **kw):
    return [await new_shipment(world, f"{tag}{i}", **kw) for i in range(n)]


def codes(responses):
    return sorted(r.status_code for r in responses)


def error_code(r):
    return r.json().get("error", {}).get("code")


async def hold(c, sid, slots):
    return await c.post(f"{API}/booking/holds", json={"shipment_id": str(sid), "slot_ids": slots})


# ------------------------------------------------------------------ (a) N simultaneous holds on one slot
@pytest.mark.parametrize("n", [10, 50])
async def test_n_simultaneous_holds_one_winner(client, world, m4, n):
    ships = await shipments(world, f"RACE{n}-", n)
    slot = m4.ids("D1", "08:00" if n == 10 else "09:00")
    clients = await coordinator(client, n)
    try:
        res = await asyncio.gather(*[hold(c, s.id, slot) for c, s in zip(clients, ships, strict=True)])
    finally:
        await close_all(clients)
    assert [r.status_code for r in res].count(201) == 1, codes(res)
    losers = [r for r in res if r.status_code != 201]
    assert len(losers) == n - 1 and {error_code(r) for r in losers} == {"SLOT_TAKEN"}, [r.text for r in losers[:2]]
    sid = uuid.UUID(slot[0])
    assert await scalar("SELECT count(*) FROM slot_claims WHERE active AND slot_id = :s", s=sid) == 1
    assert await scalar("SELECT count(*) FROM slot_holds WHERE status = 'active' AND slot_id = :s", s=sid) == 1
    assert await scalar("SELECT count(*) FROM slot_holds WHERE slot_id = :s", s=sid) == 1  # losers wrote nothing
    await assert_invariants()


# ------------------------------------------------------------------ (b) concurrent approvals
async def test_ten_concurrent_approvals_of_one_request_make_one_appointment(client, world, m4):
    s = await new_shipment(world, "APPR")
    await login(client, "coordinator")
    h = (await hold(client, s.id, m4.ids("D1", "08:00"))).json()
    req = (await client.post(f"{API}/booking/requests", json={"shipment_id": str(s.id), "hold_id": h["id"]})).json()
    clients = await clone_clients(client, 10)
    try:
        res = await asyncio.gather(*[c.post(f"{API}/booking/requests/{req['id']}/approve") for c in clients])
    finally:
        await close_all(clients)
    assert [r.status_code for r in res].count(200) == 1, codes(res)
    assert {r.status_code for r in res} <= {200, 409} and {error_code(r) for r in res if r.status_code == 409} == {"REQUEST_CLOSED"}
    assert await scalar("SELECT count(*) FROM appointments WHERE slot_id = :s", s=uuid.UUID(m4.ids("D1", "08:00")[0])) == 1
    await assert_invariants()


async def test_ten_concurrent_approvals_of_one_hold_are_idempotent(world, m4):
    s = await new_shipment(world, "HOLDAPPR")
    async with async_session_factory() as db:
        hold_row = await engine.place_hold(db, s.id, [m4.slot("D1", "08:00").id])
        await db.commit()
        hid = hold_row.id

    async def approve():
        async with async_session_factory() as db:
            a = await engine.approve_hold(db, hid)
            await db.commit()
            return a.id

    ids = await asyncio.gather(*[approve() for _ in range(10)])
    assert len(set(ids)) == 1
    assert await scalar("SELECT count(*) FROM appointments") == 1
    await assert_invariants()


# ------------------------------------------------------------------ (c) overlapping multi-window claims
async def test_overlapping_multi_window_hold_and_approval_never_both_win(client, world, m4):
    await login(client, "coordinator")
    outcomes = {"x_wins": 0, "y_wins": 0}
    for i, (a, b, c_) in enumerate((("08:00", "09:00", "10:00"), ("11:00", "12:00", "13:00"), ("14:00", "15:00", "16:00"),
                                    ("17:00", "18:00", "19:00"))):
        x, y = await new_shipment(world, f"X{i}"), await new_shipment(world, f"Y{i}")
        t0 = datetime.now(UTC)
        async with async_session_factory() as db:  # X holds [a, b], already expired but not yet swept
            hx = await engine.place_hold(db, x.id, [m4.slot("D1", a).id, m4.slot("D1", b).id], now=t0 - timedelta(minutes=20))
            rx = await engine.create_request(db, x.id, hold_id=hx.id)
            await db.commit()
            rx_id = rx.id
        clients = await clone_clients(client, 2)
        try:
            ra, rb = await asyncio.gather(clients[0].post(f"{API}/booking/requests/{rx_id}/approve"),
                                          hold(clients[1], y.id, m4.ids("D1", b, c_)))
        finally:
            await close_all(clients)
        x_ok, y_ok = ra.status_code == 200, rb.status_code == 201
        assert x_ok != y_ok, f"round {i}: both or neither won ({ra.status_code}, {rb.status_code})"
        assert (error_code(rb) if not y_ok else error_code(ra)) in {"SLOT_TAKEN", "REQUEST_CLOSED", "SLOT_UNAVAILABLE"}
        outcomes["x_wins" if x_ok else "y_wins"] += 1
        await assert_invariants()
        shared = uuid.UUID(m4.ids("D1", b)[0])
        assert await scalar("SELECT count(*) FROM slot_claims WHERE active AND slot_id = :s", s=shared) == 1
    assert sum(outcomes.values()) == 4


# ------------------------------------------------------------------ (d) sweeper racing with approval
async def test_hold_expiry_sweep_racing_with_approval(client, world, m4):
    await login(client, "coordinator")
    seen = set()
    for i, hm in enumerate(("08:00", "09:00", "10:00", "11:00", "12:00", "13:00")):
        s = await new_shipment(world, f"SWP{i}")
        t0 = datetime.now(UTC)
        async with async_session_factory() as db:
            h = await engine.place_hold(db, s.id, [m4.slot("D1", hm).id], now=t0 - timedelta(minutes=20))
            r = await engine.create_request(db, s.id, hold_id=h.id)
            await db.commit()
            rid, hid = r.id, h.id
        approver = (await clone_clients(client, 1))[0]

        async def sweep():
            async with async_session_factory() as db:
                counts = await engine.sweep(db)
                await db.commit()
                return counts

        try:
            ra, counts = await asyncio.gather(approver.post(f"{API}/booking/requests/{rid}/approve"), sweep())
        finally:
            await close_all([approver])
        assert ra.status_code in (200, 409), ra.text
        slot = uuid.UUID(m4.ids("D1", hm)[0])
        active = await scalar("SELECT count(*) FROM appointments WHERE slot_id = :s AND appointment_status IN "
                              "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')", s=slot)
        hold_status = (await rows("SELECT status FROM slot_holds WHERE id = :i", i=hid))[0][0]
        if ra.status_code == 200:
            assert active == 1 and hold_status == "converted"
        else:
            assert active == 0 and hold_status == "expired" and error_code(ra) in {"REQUEST_CLOSED", "HOLD_EXPIRED", "SLOT_TAKEN"}
        seen.add(ra.status_code)
        await assert_invariants()
    assert seen <= {200, 409}


# ------------------------------------------------------------------ (e) two drivers choose the same option
async def test_two_drivers_choosing_the_same_option(client, world, m4):
    a, b = await new_shipment(world, "DRVA"), await new_shipment(world, "DRVB")
    clients = await coordinator(client, 2)
    try:
        ra, rb = await asyncio.gather(hold(clients[0], a.id, m4.ids("D2", "09:00")), hold(clients[1], b.id, m4.ids("D2", "09:00")))
    finally:
        await close_all(clients)
    assert sorted([ra.status_code, rb.status_code]) == [201, 409]
    loser = ra if ra.status_code == 409 else rb
    assert error_code(loser) == "SLOT_TAKEN" and "taken" in loser.json()["error"]["message"].lower()
    await assert_invariants()


# ------------------------------------------------------------------ (f) the database is the backstop
async def test_database_refuses_double_allocation_even_for_raw_sql(client, world, m4):
    s1, s2 = await new_shipment(world, "DB1"), await new_shipment(world, "DB2")
    await login(client, "coordinator")
    booked = await client.post(f"{API}/booking/book", json={"shipment_id": str(s1.id), "slot_ids": m4.ids("D1", "08:00")})
    assert booked.status_code == 201
    slot, other = m4.slot("D1", "08:00").id, m4.slot("D1", "09:00").id
    now = datetime.now(UTC)

    async def attempt(sql: str, **p):
        async with async_session_factory() as db:
            with pytest.raises(IntegrityError) as exc:
                await db.execute(text(sql), p)
                await db.commit()
            return str(exc.value.orig)

    ids = lambda: uuid.uuid4()  # noqa: E731
    msg = await attempt("INSERT INTO appointments (id, code, shipment_id, slot_id, appointment_status, booking_source, is_current, "
                        "booked_at, created_at, updated_at, version) VALUES (:i, 'RAW1', :sh, :sl, 'CONFIRMED', 'PLANNER', false, "
                        ":n, :n, :n, 1)", i=ids(), sh=s2.id, sl=slot, n=now)
    assert "ux_active_appointment_per_slot" in msg
    msg = await attempt("INSERT INTO slot_claims (id, slot_id, hold_id, appointment_id, active, created_at, updated_at, version) "
                        "SELECT :i, :sl, NULL, id, true, :n, :n, 1 FROM appointments LIMIT 1", i=ids(), sl=slot, n=now)
    assert "ux_active_claim_per_slot" in msg
    # an active hold for another shipment on a slot that already has an active hold
    held = await client.post(f"{API}/booking/holds", json={"shipment_id": str(s2.id), "slot_ids": m4.ids("D2", "08:00")})
    assert held.status_code == 201
    s3 = await new_shipment(world, "DB3")
    msg = await attempt("INSERT INTO slot_holds (id, shipment_id, slot_id, extra_slot_ids, status, expires_at, created_at, updated_at, "
                        "version) VALUES (:i, :sh, :sl, '[]', 'active', :e, :n, :n, 1)", i=ids(), sh=s3.id, sl=m4.slot("D2", "08:00").id,
                        n=now, e=now + timedelta(minutes=15))
    assert "ux_active_hold_per_slot" in msg
    msg = await attempt("INSERT INTO slot_claims (id, slot_id, hold_id, appointment_id, active, created_at, updated_at, version) "
                        "SELECT :i, slot_id, id, NULL, true, :n, :n, 1 FROM slot_holds WHERE status = 'active' LIMIT 1",
                        i=ids(), n=now)
    assert "ux_active_claim_per_slot" in msg
    # one shipment, two active holds
    msg = await attempt("INSERT INTO slot_holds (id, shipment_id, slot_id, extra_slot_ids, status, expires_at, created_at, updated_at, "
                        "version) VALUES (:i, :sh, :sl, '[]', 'active', :e, :n, :n, 1)", i=ids(), sh=s2.id, sl=other, n=now,
                        e=now + timedelta(minutes=15))
    assert "ux_active_hold_per_shipment" in msg
    # one shipment, two current active appointments
    msg = await attempt("INSERT INTO appointments (id, code, shipment_id, slot_id, appointment_status, booking_source, is_current, "
                        "booked_at, created_at, updated_at, version) VALUES (:i, 'RAW2', :sh, :sl, 'CONFIRMED', 'PLANNER', true, "
                        ":n, :n, :n, 1)", i=ids(), sh=s1.id, sl=other, n=now)
    assert "ux_current_active_appointment_per_shipment" in msg
    # overlapping slot window on the same dock
    msg = await attempt("INSERT INTO appointment_slots (id, code, facility_id, dock_id, slot_start_ts, slot_end_ts, slot_status, "
                        "created_at, updated_at, version) SELECT :i, 'RAWSLOT', facility_id, dock_id, slot_start_ts + interval '30 minutes', "
                        "slot_end_ts + interval '30 minutes', 'OPEN', :n, :n, 1 FROM appointment_slots WHERE id = :sl",
                        i=ids(), sl=slot, n=now)
    assert "ex_slot_no_overlap" in msg
    await assert_invariants()


# ------------------------------------------------------------------ (g) no deadlocks on overlapping windows
async def test_no_deadlock_on_overlapping_two_slot_windows(client, world, m4):
    n = 20
    ships = await shipments(world, "DLK", n)
    hours = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00"]
    clients = await coordinator(client, n)
    try:
        res = await asyncio.gather(*[
            hold(c, s.id, m4.ids("D1", hours[i % 6], hours[i % 6 + 1])) for i, (c, s) in enumerate(zip(clients, ships, strict=True))])
    finally:
        await close_all(clients)
    assert {r.status_code for r in res} <= {201, 409}, [r.text for r in res if r.status_code not in (201, 409)][:2]
    assert not any("deadlock" in r.text.lower() for r in res)
    wins = [r for r in res if r.status_code == 201]
    assert 1 <= len(wins) <= 3, "overlapping windows can never both succeed (max 3 disjoint pairs among 7 hours)"
    assert {error_code(r) for r in res if r.status_code == 409} <= {"SLOT_TAKEN"}
    claimed = await scalar("SELECT count(*) FROM slot_claims WHERE active AND hold_id IS NOT NULL")
    assert claimed == 2 * len(wins)
    await assert_invariants()
