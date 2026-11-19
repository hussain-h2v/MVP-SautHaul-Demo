"""Milestone 9: analytics views (KPI maths on hand-built data, scoping, periods, CSV), AI narratives (de-identified, graceful
when AI is off, cached) and the proposal-only optimiser (never writes)."""
import itertools
import json
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core import periods
from app.core.db import async_session_factory
from app.core.errors import ValidationAppError
from app.modules.appointments.models import Appointment, FacilityCheckin
from app.modules.booking.models import ApprovalRequest, Escalation
from app.modules.docks.models import Dock
from app.modules.eta.models import EtaUpdate
from app.modules.slots.models import AppointmentSlot
from app.modules.whatsapp.models import ChatThread
from tests.conftest import login
from tests.m4_helpers import at, m4, new_shipment, orm_book  # noqa: F401
from tests.test_m7_admin import chain, setup_mock

IST = ZoneInfo("Asia/Kolkata")
_n = itertools.count(1)
YESTERDAY = datetime.now(IST).date() - timedelta(days=1)


def ist(h: int, m: int = 0) -> datetime:
    return datetime.combine(YESTERDAY, time(h, m), tzinfo=IST).astimezone(UTC)


async def as_(client, who):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await login(client, who)


PERIOD = {"range": "custom", "date_from": ist(0).isoformat(), "date_to": (ist(0) + timedelta(days=1)).isoformat()}


async def slot(fac_id, dock_id, start: datetime, status: str = "OPEN") -> AppointmentSlot:
    async with async_session_factory() as db:
        s = AppointmentSlot(code=f"T9-{next(_n)}", facility_id=fac_id, dock_id=dock_id, slot_start_ts=start, slot_end_ts=start + timedelta(hours=1), slot_status=status)
        db.add(s)
        await db.commit()
        return s


async def visit(fac_id, dock_id, shipment_id, start: datetime, status: str, gate_in=None, unload_start=None, gate_out=None) -> None:
    s = await slot(fac_id, dock_id, start)
    async with async_session_factory() as db:
        db.add(Appointment(code=f"T9A{next(_n)}", shipment_id=shipment_id, slot_id=s.id, appointment_status=status, booking_source="PLANNER",
                           booked_at=start - timedelta(days=1), is_current=status != "CANCELLED"))
        if gate_in:
            db.add(FacilityCheckin(shipment_id=shipment_id, facility_id=fac_id, gate_in_ts=gate_in, unload_start_ts=unload_start, gate_out_ts=gate_out, queue_state="COMPLETED"))
        await db.commit()


async def extra_shipment(world, tag: str):
    return await new_shipment(world, tag)


@pytest.fixture
async def data(world, m4):
    """Facility A, yesterday: two completed visits (one on time, one late), one no-show, one cancelled, five slots; plus one late
    completed visit at facility B for carrier B."""
    d1 = m4.docks["D1"].id
    s_ok, s_late, s_ns, s_cx = [await extra_shipment(world, t) for t in ("OK", "LATE", "NS", "CX")]
    await visit(world.facility_a.id, d1, s_ok.id, ist(10), "COMPLETED", gate_in=ist(9, 55), unload_start=ist(10, 10), gate_out=ist(11, 10))      # wait 15, dwell 75
    await visit(world.facility_a.id, d1, s_late.id, ist(11), "COMPLETED", gate_in=ist(11, 40), unload_start=ist(11, 50), gate_out=ist(13, 10))  # late 40, wait 10, dwell 90
    await visit(world.facility_a.id, d1, s_ns.id, ist(12), "NO_SHOW")
    await visit(world.facility_a.id, d1, s_cx.id, ist(13), "CANCELLED")
    await slot(world.facility_a.id, d1, ist(14))  # open and unused
    async with async_session_factory() as db:
        dock_b = Dock(code="FAC-B-B1", facility_id=world.facility_b.id, dock_code="B1", dock_type="STANDARD", max_vehicle_weight_kg=30000)
        db.add(dock_b)
        await db.commit()
    await visit(world.facility_b.id, dock_b.id, world.shipment_b.id, ist(9), "COMPLETED", gate_in=ist(10, 30), unload_start=ist(10, 45), gate_out=ist(11, 30))
    return SimpleNamespace(ok=s_ok, late=s_late, ns=s_ns, cx=s_cx)


def kv(res, key):
    return res["kpis"][key]["value"]


# ---------------------------------------------------------------- periods
def test_period_windows_buckets_and_previous():
    now = datetime(2026, 11, 18, 17, 0, tzinfo=UTC)  # 22:30 IST
    p1 = periods.resolve("1d", None, None, now)
    assert p1.bucket == "hour" and p1.end > now and (p1.end - p1.start) == timedelta(days=1, minutes=1) and len(p1.labels()) in (24, 25, 26)
    p7 = periods.resolve("7d", None, None, now)
    assert p7.bucket == "day" and p7.start == datetime(2026, 11, 11, 18, 30, tzinfo=UTC) and len(p7.labels()) == 7
    assert periods.resolve("3d", None, None, now).bucket == "hour"
    assert len(periods.resolve("3w", None, None, now).labels()) == 21 and len(periods.resolve("1m", None, None, now).labels()) == 30
    assert p7.previous.end == p7.start and p7.previous.span == p7.span
    c = periods.resolve("custom", now - timedelta(days=2), now, now)
    assert c.key == "custom" and c.bucket == "hour"
    for bad in (("custom", None, None), ("custom", now, now - timedelta(days=1)), ("year", None, None), ("custom", now - timedelta(days=400), now)):
        with pytest.raises(ValidationAppError):
            periods.resolve(*bad, now)


# ---------------------------------------------------------------- KPI maths
async def test_facility_kpis_match_hand_computed_values(client, world, m4, data):
    await as_(client, "admin")
    r = (await client.get("/api/v1/analytics/views/facility", params={**PERIOD, "facility_id": str(world.facility_a.id)})).json()
    assert kv(r, "on_time_rate") == 50.0
    assert kv(r, "avg_wait_min") == 12.5 and kv(r, "avg_dwell_min") == 82.5
    assert kv(r, "no_show_rate") == 33.3  # 1 of 3 (the cancelled booking is not scheduled demand)
    assert kv(r, "loads_completed") == 2
    assert kv(r, "utilisation_pct") == 40.0  # 120 booked of 300 bookable minutes
    assert r["extra"]["arrivals"] == 2 and r["extra"]["late"] == 1 and r["extra"]["scheduled"] == 3
    row = r["tables"]["by_dock"][0]
    assert row["dock"] == "D1" and row["available_min"] == 300 and row["booked_min"] == 120
    assert sum(s["arrivals"] for s in r["series"]) == 2 and sum(s["no_shows"] for s in r["series"]) == 1
    assert [h["hour"] for h in r["tables"]["heatmap"]] == [10, 11, 12, 13, 14]  # every open or booked slot counts as capacity


async def test_previous_period_comparison(client, world, m4, data):
    await as_(client, "admin")
    p = {"range": "custom", "date_from": ist(0).isoformat(), "date_to": (ist(0) + timedelta(days=1)).isoformat()}
    r = (await client.get("/api/v1/analytics/views/network", params=p)).json()
    k = r["kpis"]["loads_completed"]
    assert k["value"] == 3 and k["previous"] == 0 and k["change"] is None  # nothing before: no percentage rather than infinity
    assert r["period"]["range"] == "custom" and r["period"]["bucket"] == "hour" and len(r["series"]) >= 24


async def test_requests_escalations_delays_and_bot_resolution(client, world, m4, data):
    async with async_session_factory() as db:
        sid = world.shipment_a.id
        db.add_all([
            ApprovalRequest(shipment_id=sid, status="approved", created_at=ist(9), decided_at=ist(9, 20), updated_at=ist(9, 20)),
            ApprovalRequest(shipment_id=sid, status="approved", created_at=ist(10), decided_at=ist(10, 10), updated_at=ist(10, 10)),
            ApprovalRequest(shipment_id=sid, status="rejected", created_at=ist(11), decided_at=ist(11, 30), updated_at=ist(11, 30)),
            ApprovalRequest(shipment_id=sid, status="waiting", created_at=ist(12), updated_at=ist(12)),
            Escalation(shipment_id=sid, reason_code="NO_FEASIBLE_SLOT", handoff_record={}, status="resolved", created_at=ist(9), closed_at=ist(9, 40), updated_at=ist(9, 40)),
            Escalation(shipment_id=sid, reason_code="DISPUTE", handoff_record={}, status="open", created_at=ist(10), updated_at=ist(10)),
            EtaUpdate(shipment_id=sid, source_type="DRIVER_DECLARED", declared_eta_ts=world.shipment_a.original_eta_ts + timedelta(minutes=90), delay_reason_code="TRAFFIC", created_at=ist(8), updated_at=ist(8)),
            EtaUpdate(shipment_id=sid, source_type="DRIVER_DECLARED", declared_eta_ts=world.shipment_a.original_eta_ts + timedelta(minutes=30), delay_reason_code="BREAKDOWN", created_at=ist(8, 30), updated_at=ist(8, 30)),
            EtaUpdate(shipment_id=sid, source_type="ORIGINAL_PLAN", declared_eta_ts=world.shipment_a.original_eta_ts, created_at=ist(8), updated_at=ist(8)),
        ])
        for tag, status in (("1", "RESOLVED"), ("2", "ESCALATED")):
            db.add(ChatThread(code=f"T9T{tag}", driver_id=world.shipment_a.driver_id, shipment_id=sid, opened_at=ist(9), thread_status=status, thread_intent="REPORT_DELAY", created_at=ist(9), updated_at=ist(9)))
        await db.commit()
    await as_(client, "coordinator")
    r = (await client.get("/api/v1/analytics/views/coordinator", params=PERIOD)).json()
    assert kv(r, "requests") == 4 and kv(r, "backlog") == 1
    assert kv(r, "avg_decision_min") == round((20 + 10 + 30) / 3, 1)  # only decided requests
    assert kv(r, "escalations") == 2 and kv(r, "avg_resolution_min") == 40.0
    assert {m["key"]: m["count"] for m in r["tables"]["request_mix"]} == {"approved": 2, "rejected": 1, "waiting": 1}
    assert {e["key"]: e["count"] for e in r["tables"]["escalation_reasons"]} == {"NO_FEASIBLE_SLOT": 1, "DISPUTE": 1}
    assert kv(r, "bot_resolution_rate") == 50.0
    n = (await client.get("/api/v1/analytics/views/network", params=PERIOD)).json()
    causes = {c["key"]: c for c in n["tables"]["delay_causes"]}
    assert set(causes) == {"TRAFFIC", "BREAKDOWN"} and causes["TRAFFIC"]["avg_delay_min"] == 90.0 and kv(n, "delay_reports") == 2  # original plan rows are not driver reports


# ---------------------------------------------------------------- scoping
async def test_scope_isolation_between_roles(client, world, m4, data):
    fa, fb = str(world.facility_a.id), str(world.facility_b.id)
    await as_(client, "admin")
    assert kv((await client.get("/api/v1/analytics/views/network", params=PERIOD)).json(), "loads_completed") == 3
    assert kv((await client.get("/api/v1/analytics/views/facility", params={**PERIOD, "facility_id": fb})).json(), "loads_completed") == 1

    await as_(client, "facility_planner")  # scoped to facility A
    mine = (await client.get("/api/v1/analytics/views/facility", params=PERIOD)).json()
    assert kv(mine, "loads_completed") == 2 and {r["facility"] for r in mine["tables"]["by_dock"]} == {"Facility A"}
    assert (await client.get("/api/v1/analytics/views/facility", params={**PERIOD, "facility_id": fb})).status_code == 404
    assert (await client.get("/api/v1/analytics/views/network", params=PERIOD)).status_code == 403
    assert (await client.get("/api/v1/analytics/views/coordinator", params=PERIOD)).status_code == 403
    assert (await client.get("/api/v1/analytics/views/carrier", params=PERIOD)).status_code == 403

    await as_(client, "carrier_user")  # carrier A
    a = (await client.get("/api/v1/analytics/views/carrier", params=PERIOD)).json()
    assert kv(a, "arrivals") == 2
    spoof = (await client.get("/api/v1/analytics/views/carrier", params={**PERIOD, "carrier_id": str(world.carrier_b.id)})).json()
    assert kv(spoof, "arrivals") == 2  # a requested carrier_id is ignored: identity comes from the session
    assert (await client.get("/api/v1/analytics/views/facility", params=PERIOD)).status_code == 403
    assert (await client.get("/api/v1/analytics/views/network", params=PERIOD)).status_code == 403

    await as_(client, "carrier_b")
    assert kv((await client.get("/api/v1/analytics/views/carrier", params=PERIOD)).json(), "arrivals") == 1
    await as_(client, "admin")
    assert kv((await client.get("/api/v1/analytics/views/carrier", params={**PERIOD, "carrier_id": str(world.carrier_b.id)})).json(), "arrivals") == 1
    assert (await client.get("/api/v1/analytics/views/nope", params=PERIOD)).status_code == 404
    assert (await client.get("/api/v1/analytics/views/network", params={"range": "year"})).status_code == 422


async def test_carrier_patterns_by_driver_and_lane(client, world, m4, data):
    await as_(client, "carrier_user")
    r = (await client.get("/api/v1/analytics/views/carrier", params=PERIOD)).json()
    lanes = r["tables"]["by_lane"]
    assert lanes[0]["origin"] == "Delhi" and lanes[0]["trips"] == 2 and lanes[0]["late"] == 1 and lanes[0]["late_rate"] == 50.0
    drivers = {d["driver"]: d for d in r["tables"]["by_driver"]}
    assert len(drivers) == 2 and sum(d["late"] for d in drivers.values()) == 1
    assert kv(r, "slot_moves") == 0 and kv(r, "decline_rate") == 0.0


# ---------------------------------------------------------------- csv
async def test_csv_export_respects_scope_and_validates_table(client, world, m4, data):
    await as_(client, "facility_planner")
    r = await client.get("/api/v1/analytics/views/facility/export.csv", params={**PERIOD, "table": "by_dock"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "facility,dock,type,available_min,booked_min,utilisation_pct" and len(lines) == 2 and "Facility A" in lines[1] and "Facility B" not in r.text
    assert (await client.get("/api/v1/analytics/views/facility/export.csv", params={**PERIOD, "table": "by_driver"})).status_code == 422
    s = await client.get("/api/v1/analytics/views/facility/export.csv", params={**PERIOD, "table": "series"})
    assert s.text.splitlines()[0].startswith("bucket,arrivals,late") and len(s.text.splitlines()) > 20
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/analytics/views/facility/export.csv", params=PERIOD)).status_code == 403


# ---------------------------------------------------------------- AI narratives
async def test_narrative_without_ai_returns_flag_not_error(client, world, m4, data):
    await as_(client, "admin")
    r = await client.get("/api/v1/insights/narrative", params={"view": "network", **PERIOD})
    assert r.status_code == 200
    j = r.json()
    assert j["ai_available"] is False and j["text"] is None and j["task"] == "dock_insight"
    assert (await client.get("/api/v1/insights/narrative", params={"view": "bogus"})).status_code == 404


async def test_narrative_sends_only_aggregates_and_is_cached(client, world, m4, data, monkeypatch):
    from app.core.idempotency import get_redis
    from app.modules.ai import AIResult
    from app.modules.insights import service as insights_service

    r = get_redis()
    for k in [k async for k in r.scan_iter("insight:*")]:
        await r.delete(k)  # narratives are cached for ten minutes: start clean
    await r.aclose()

    sent: list[list[dict]] = []
    calls = {"n": 0}

    async def fake(task, messages, **kw):
        calls["n"] += 1
        sent.append(messages)
        return AIResult(text="- On-time arrivals are at 50%.", provider="p", model="m")

    monkeypatch.setattr(insights_service, "run_or_none", fake)
    await as_(client, "carrier_user")
    p = {"view": "carrier", **PERIOD}
    a = (await client.get("/api/v1/insights/narrative", params=p)).json()
    b = (await client.get("/api/v1/insights/narrative", params=p)).json()
    assert a["ai_available"] and a["task"] == "driver_insight" and a["cached"] is False and b["cached"] is True and calls["n"] == 1
    blob = json.dumps(sent[0])
    for forbidden in ("Driver A", "Driver B", "M4 Driver", "SHP-", "M4-", "+9188", "Carrier A", "Facility A", "Delhi"):
        assert forbidden not in blob, forbidden
    assert "<figures>" in blob and "on_time_rate" in blob and "rank" in blob
    await as_(client, "coordinator")
    c = (await client.get("/api/v1/insights/narrative", params={"view": "coordinator", **PERIOD})).json()
    assert c["task"] == "summarise" and calls["n"] == 2  # different view, different cache entry
    await as_(client, "facility_planner")
    assert (await client.get("/api/v1/insights/narrative", params={"view": "network", **PERIOD})).status_code == 403  # same scope rules as the numbers


async def test_narrative_through_the_real_router_with_the_offline_model(client, world, m4, data):
    await as_(client, "admin")
    _, ids = await setup_mock(client)
    await chain(client, "dock_insight", ids["mock-primary"])
    j = (await client.get("/api/v1/insights/narrative", params={"view": "facility", **PERIOD, "facility_id": str(world.facility_a.id)})).json()
    assert j["ai_available"] is True and "On-time arrivals" in j["text"] and j["model"] == "mock-primary"
    logged = (await client.get("/api/v1/ai/logs", params={"task": "dock_insight"})).json()
    assert logged["total"] == 1  # the narrative shows up in AI monitoring like any other call


# ---------------------------------------------------------------- optimiser
async def _optimiser_world(world, m4):
    async with async_session_factory() as db:  # only D1 is usable, so loads compete for its slots
        await db.execute(text("UPDATE appointment_slots SET slot_status = 'BLOCKED' WHERE dock_id <> :d"), {"d": m4.docks["D1"].id})
        await db.commit()
    low = await new_shipment(world, "LOW", priority="LOW", eta=at("09:00"))
    crit = await new_shipment(world, "CRIT", priority="CRITICAL", eta=at("09:00"))
    t0 = datetime.now(UTC)
    a_low = await orm_book(low.id, m4.slot("D1", "09:00").id, booked_at=t0 - timedelta(hours=5))
    a_crit = await orm_book(crit.id, m4.slot("D1", "10:00").id, booked_at=t0 - timedelta(hours=1))
    return low, crit, a_low, a_crit


async def test_optimiser_proposes_priority_first_and_never_writes(client, world, m4):
    low, crit, a_low, a_crit = await _optimiser_world(world, m4)
    snapshot_sql = ("SELECT (SELECT count(*) FROM appointments), (SELECT count(*) FROM slot_claims), (SELECT count(*) FROM slot_holds), "
                    "(SELECT count(*) FROM audit_log), (SELECT string_agg(id::text || slot_id::text || appointment_status || version::text, ',' ORDER BY id) FROM appointments)")

    async def snap():
        async with async_session_factory() as db:
            return tuple((await db.execute(text(snapshot_sql))).one())

    await as_(client, "facility_planner")  # log in first: the login itself is audited
    before = await snap()
    r = await client.get("/api/v1/insights/optimiser/proposal", params={"facility_id": str(world.facility_a.id), "day": at("09:00").astimezone(IST).date().isoformat()})
    assert r.status_code == 200
    j = r.json()
    assert j["writes"] == 0 and j["movable"] == 2 and j["better_than_current"] is True
    cards = j["scorecards"]
    assert cards["current"]["priority_weighted_wait"] == 240 and cards["proposed"]["priority_weighted_wait"] == 60 and j["saved_weighted_wait"] == 180
    assert cards["proposed"]["unplaced"] == 0 and cards["fcfs"]["priority_weighted_wait"] == 240  # first come first served keeps the low-priority load first
    moves = {m["shipment"]: m for m in j["moves"]}
    assert moves["M4-CRIT"]["to_dock"] == "D1" and moves["M4-CRIT"]["wait_after_min"] == 0 and moves["M4-CRIT"]["changes"] is True
    assert moves["M4-LOW"]["wait_after_min"] == 60
    assert await snap() == before  # not one row, claim, hold, audit entry or version changed


async def test_optimiser_leaves_started_and_arrived_loads_fixed(client, world, m4):
    low, crit, a_low, a_crit = await _optimiser_world(world, m4)
    async with async_session_factory() as db:
        db.add(FacilityCheckin(shipment_id=low.id, facility_id=world.facility_a.id, gate_in_ts=at("08:50"), queue_state="WAITING_EARLY"))
        await db.commit()
    await as_(client, "admin")
    j = (await client.get("/api/v1/insights/optimiser/proposal", params={"facility_id": str(world.facility_a.id), "day": at("09:00").astimezone(IST).date().isoformat()})).json()
    assert j["movable"] == 1 and j["fixed_slots"] == 1 and [m["shipment"] for m in j["moves"]] == ["M4-CRIT"]
    assert j["moves"][0]["to_start"] == at("10:00").isoformat().replace("+00:00", "+00:00") or j["moves"][0]["changes"] is False  # 09:00 is held by the load already at the gate


async def test_optimiser_scope_and_roles(client, world, m4):
    await as_(client, "facility_planner")
    assert (await client.get("/api/v1/insights/optimiser/proposal", params={"facility_id": str(world.facility_b.id)})).status_code == 404
    await as_(client, "carrier_user")
    assert (await client.get("/api/v1/insights/optimiser/proposal", params={"facility_id": str(world.facility_a.id)})).status_code == 403
    await as_(client, "admin")
    empty = (await client.get("/api/v1/insights/optimiser/proposal", params={"facility_id": str(world.facility_b.id), "day": "2031-01-01"})).json()
    assert empty["movable"] == 0 and empty["writes"] == 0


async def test_ai_usage_map_marks_insight_tasks_wired(client, world):
    await as_(client, "admin")
    m = (await client.get("/api/v1/ai/usage-map")).json()
    by = {i["task"]: i for i in m["items"]}
    assert by["driver_insight"]["status"] == "wired" and by["dock_insight"]["status"] == "wired" and by["summarise"]["status"] == "wired"
    assert "figures" in by["dock_insight"]["input"].lower() or "aggregate" in by["dock_insight"]["input"].lower()


async def test_network_view_includes_ai_spend_through_the_ai_service(client, world):
    await as_(client, "admin")
    n = (await client.get("/api/v1/analytics/views/network", params={"range": "7d"})).json()
    assert set(n["ai_spend"]) >= {"today", "month_to_date", "projected_month"}
    await as_(client, "coordinator")
    assert "ai_spend" in (await client.get("/api/v1/analytics/views/network", params={"range": "7d"})).json()
