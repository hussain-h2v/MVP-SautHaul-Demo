"""Pure unit tests: every feasibility rule, option building, ranking policy. No database."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.scheduling import feasibility as f
from app.modules.scheduling.feasibility import DockFacts, EventFacts, FacilityFacts, ShipmentFacts, SlotFacts
from app.modules.scheduling.ranking import RequestFacts, rank_options, rank_requests

IST = ZoneInfo("Asia/Kolkata")
DAY = datetime(2026, 12, 1, tzinfo=IST)


def at(h, m=0) -> datetime:
    return DAY.replace(hour=h, minute=m).astimezone(UTC)


def ship(**kw) -> ShipmentFacts:
    base = dict(id="S1", facility_id="F", vehicle_type_code="TRUCK", required_dock_type="ANY",
                temperature_control_required=False, load_weight_kg=8000, expected_unload_min=60, priority_code="NORMAL")
    return ShipmentFacts(**{**base, **kw})


def dock(id="D1", code="D1", type="STANDARD", **kw) -> DockFacts:
    base = dict(status="ACTIVE", supports_refrigerated=type == "REEFER", max_weight_kg=30000)
    return DockFacts(id=id, code=code, dock_type=type, **{**base, **kw})


def slots(dock_id="D1", start_h=8, n=4, minutes=60, status="OPEN", prefix=None):
    out, t = [], at(start_h)
    for i in range(n):
        out.append(SlotFacts(f"{prefix or dock_id}-{i}", dock_id, t, t + timedelta(minutes=minutes), status))
        t += timedelta(minutes=minutes)
    return out


FAC = FacilityFacts(tz="Asia/Kolkata", open_time=time(6), close_time=time(22), last_start=time(21), heavy_kg=25000)


def build(shipment=None, docks=None, sl=None, events=(), occupied=frozenset(), eta=None, latest_finish=None, fac=FAC):
    return f.build_options(shipment or ship(), fac, docks or [dock()], sl or slots(), list(events), set(occupied),
                           eta=eta, latest_finish=latest_finish)


def codes(opts):
    return [o.slot_ids for o in opts]


# ---------------- rule 1: ETA ----------------
def test_slots_before_eta_are_rejected_and_boundary_is_allowed():
    opts, rej = build(eta=at(9))
    assert codes(opts) == [("D1-1",), ("D1-2",), ("D1-3",)]  # the 09:00 slot starts exactly at the ETA
    assert rej["BEFORE_ETA"] == 1


def test_no_eta_means_no_eta_constraint():
    opts, _ = build(eta=None)
    assert len(opts) == 4


# ---------------- rule 2: compatibility ----------------
@pytest.mark.parametrize("required,dock_type,ok", [
    ("REEFER", "REEFER", True), ("REEFER", "STANDARD", False), ("HEAVY", "HEAVY", True),
    ("HEAVY", "STANDARD", False), ("STANDARD", "HEAVY", False), ("ANY", "HEAVY", True), ("ANY", "REEFER", True)])
def test_dock_type_matrix(required, dock_type, ok):
    opts, rej = build(ship(required_dock_type=required), [dock(type=dock_type)])
    assert bool(opts) is ok
    if not ok:
        assert rej[f"NEEDS_{required}_DOCK"] == 4


def test_temperature_controlled_load_needs_refrigerated_dock():
    opts, rej = build(ship(temperature_control_required=True), [dock(type="STANDARD", supports_refrigerated=False)])
    assert not opts and rej["NEEDS_REFRIGERATED_DOCK"] == 4
    opts, _ = build(ship(temperature_control_required=True), [dock(type="STANDARD", supports_refrigerated=True)])
    assert opts


def test_weight_limit_and_heavy_rule():
    opts, rej = build(ship(load_weight_kg=40000), [dock(max_weight_kg=30000)])
    assert not opts and rej["LOAD_EXCEEDS_DOCK_LIMIT"] == 4
    opts, rej = build(ship(load_weight_kg=26000), [dock(type="STANDARD")])  # >= heavy rule 25000 -> heavy dock only
    assert not opts and rej["NEEDS_HEAVY_DOCK"] == 4
    opts, _ = build(ship(load_weight_kg=26000), [dock(type="HEAVY", id="H", code="H")], slots("H"))
    assert opts


def test_inactive_dock_and_vehicle_type_restriction():
    opts, rej = build(docks=[dock(status="MAINTENANCE")])
    assert not opts and rej["DOCK_NOT_ACTIVE"] == 4
    opts, rej = build(docks=[dock(compatible_vehicle_types=("VAN",))])
    assert not opts and rej["VEHICLE_TYPE_NOT_ALLOWED"] == 4
    assert build(docks=[dock(compatible_vehicle_types=("TRUCK",))])[0]
    assert build(ship(vehicle_type_code=None), [dock(compatible_vehicle_types=("VAN",))])[0]  # unknown vehicle: no restriction


# ---------------- rule 3: duration and combining ----------------
def test_long_unload_combines_consecutive_windows():
    opts, _ = build(ship(expected_unload_min=100))
    assert codes(opts) == [("D1-0", "D1-1"), ("D1-1", "D1-2"), ("D1-2", "D1-3")]
    assert "COMBINES_2_WINDOWS" in opts[0].reasons and opts[0].wasted_min == 20


def test_too_long_even_when_combined_is_rejected():
    opts, rej = build(ship(expected_unload_min=250), sl=slots(n=4))
    assert not opts and rej["TOO_SHORT"] > 0


def test_non_consecutive_slots_are_not_combined():
    sl = slots(n=1) + [SlotFacts("gap", "D1", at(10), at(11), "OPEN")]
    opts, rej = build(ship(expected_unload_min=100), sl=sl)
    assert not opts


def test_heavy_dock_90_minute_windows():
    opts, _ = build(ship(expected_unload_min=80, load_weight_kg=26000), [dock("H", "H", "HEAVY")], slots("H", minutes=90, n=3))
    assert len(opts) == 3 and opts[0].wasted_min == 10 and len(opts[0].slot_ids) == 1


# ---------------- rule 4: blocked slots and dock events ----------------
def test_blocked_slot_and_events():
    sl = slots()
    sl[1] = SlotFacts("D1-1", "D1", sl[1].start, sl[1].end, "BLOCKED")
    opts, rej = build(sl=sl)
    assert [o.slot_ids[0] for o in opts] == ["D1-0", "D1-2", "D1-3"] and rej["SLOT_BLOCKED"] == 1
    ev = EventFacts("D1", "BREAKDOWN", at(9, 30), at(11, 30))
    opts, rej = build(events=[ev])
    assert [o.slot_ids[0] for o in opts] == ["D1-0"] and rej["DOCK_EVENT"] == 3  # 09:00-10:00 overlaps 09:30


@pytest.mark.parametrize("etype,blocks", [("BREAKDOWN", True), ("MAINTENANCE", True), ("CAPACITY_REDUCTION", True),
                                           ("MANUAL_BLOCK", True), ("REOPENED", False)])
def test_event_types(etype, blocks):
    opts, _ = build(events=[EventFacts("D1", etype, at(8), at(12))])
    assert (not opts) is blocks


def test_open_ended_event_and_event_on_other_dock():
    assert not build(events=[EventFacts("D1", "BREAKDOWN", at(7), None)])[0]
    assert build(events=[EventFacts("OTHER", "BREAKDOWN", at(7), None)])[0]
    assert len(build(events=[EventFacts("D1", "BREAKDOWN", at(7), at(8, 30))])[0]) == 3  # overlaps the 08:00 slot
    assert len(build(events=[EventFacts("D1", "BREAKDOWN", at(6), at(8))])[0]) == 4  # ends exactly at 08:00: no overlap


# ---------------- rule 5: hours and planner approval ----------------
def test_operating_hours_and_after_hours_start():
    opts, rej = build(sl=slots(start_h=5, n=2))  # 05:00 start is before opening
    assert [o.slot_ids[0] for o in opts] == ["D1-1"] and rej["OUTSIDE_HOURS"] == 1
    opts, rej = build(sl=slots(start_h=21, n=2))  # 21:00-22:00 ok, 22:00-23:00 ends after close
    assert len(opts) == 1 and rej["OUTSIDE_HOURS"] == 1


def test_start_after_last_new_start_needs_planner_approval():
    fac = FacilityFacts(tz="Asia/Kolkata", open_time=time(6), close_time=time(23, 59), last_start=time(21), heavy_kg=None)
    opts, _ = build(sl=slots(start_h=20, n=3), fac=fac)
    flags = {o.slot_ids[0]: o.needs_planner_approval for o in opts}
    assert flags == {"D1-0": False, "D1-1": False, "D1-2": True}  # 21:00 is allowed, 22:00 needs approval
    assert "NEEDS_PLANNER_APPROVAL" in opts[2].reasons
    assert not f.needs_planner_approval(slots(start_h=23, n=1), FacilityFacts("Asia/Kolkata", time(6), time(23, 59), None, None))


# ---------------- rule 6/7: deadline and occupancy ----------------
def test_latest_finish_deadline():
    opts, rej = build(latest_finish=at(10))
    assert [o.slot_ids[0] for o in opts] == ["D1-0", "D1-1"] and rej["MISSES_DEADLINE"] == 2
    assert "MEETS_FINISH_DEADLINE" in opts[0].reasons


def test_occupied_slots_are_excluded_and_run_problems_list_everything():
    opts, rej = build(occupied={"D1-0", "D1-1"})
    assert [o.slot_ids[0] for o in opts] == ["D1-2", "D1-3"] and rej["OCCUPIED"] == 2
    run = slots(start_h=5, n=1, minutes=30, status="CLOSED")
    probs = f.run_problems(run, ship(), FAC, [EventFacts("D1", "BREAKDOWN", at(5), None)], {"D1-0"}, eta=at(6), latest_finish=at(5, 10))
    assert set(probs) == {"BEFORE_ETA", "TOO_SHORT", "SLOT_BLOCKED", "OCCUPIED", "DOCK_EVENT", "OUTSIDE_HOURS", "MISSES_DEADLINE"}


def test_not_consecutive_run_is_reported():
    run = [SlotFacts("a", "D1", at(8), at(9), "OPEN"), SlotFacts("b", "D1", at(10), at(11), "OPEN")]
    assert "NOT_CONSECUTIVE" in f.run_problems(run, ship(), FAC, [], set(), eta=None, latest_finish=None)


def test_midnight_crossing_is_outside_hours():
    run = [SlotFacts("a", "D1", at(23), at(23) + timedelta(hours=2), "OPEN")]
    assert "OUTSIDE_HOURS" in f.run_problems(run, ship(), FAC, [], set(), eta=None, latest_finish=None)


def test_docks_without_slots_are_skipped():
    opts, rej = build(docks=[dock("D1"), dock("D2", "D2")])
    assert len(opts) == 4 and not rej


# ---------------- option ranking ----------------
def test_rank_options_prefers_approval_free_then_earliest_then_least_waste():
    fac = FacilityFacts(tz="Asia/Kolkata", open_time=time(6), close_time=time(23, 59), last_start=time(21), heavy_kg=None)
    sl = slots("D1", 20, 3) + slots("D2", 20, 2, minutes=90, prefix="B")
    opts, _ = build(docks=[dock("D1"), dock("D2", "D2")], sl=sl, fac=fac, eta=at(20))
    ranked = rank_options(opts, eta=at(20), tz=IST)
    assert [o.rank for o in ranked] == list(range(1, len(ranked) + 1))
    assert ranked[0].needs_planner_approval is False and ranked[-1].needs_planner_approval is True
    assert ranked[0].dock_code == "D1" and "Earliest compatible slot after the 20:00 ETA" in ranked[0].explanation
    assert any("planner approval" in o.explanation for o in ranked if o.needs_planner_approval)
    assert "Starts" in ranked[1].explanation and "spare" in ranked[1].explanation or "after the best option" in ranked[1].explanation


def test_rank_options_explains_combined_windows():
    opts, _ = build(ship(expected_unload_min=100), eta=at(8))
    ranked = rank_options(opts, eta=at(8), tz=IST)
    assert "combines consecutive windows" in ranked[0].explanation


# ---------------- competing request ranking ----------------
NOW = at(7)


def req(id, prio="NORMAL", start_h=9, **kw):
    return RequestFacts(id=id, priority_code=prio, option_start=at(start_h), **kw)


def order(rs, weights=None):
    return [r.id for r in rank_requests(rs, now=NOW, weights=weights)]


def test_unloading_trucks_are_fixed_first_even_over_critical():
    assert order([req("crit", "CRITICAL"), req("unloading", "LOW", is_unloading=True)]) == ["unloading", "crit"]


def test_priority_then_lost_appointment_then_waiting_then_start():
    assert order([req("low", "LOW"), req("crit", "CRITICAL"), req("high", "HIGH")]) == ["crit", "high", "low"]
    assert order([req("a"), req("lost", lost_appointment=True)]) == ["lost", "a"]
    assert order([req("short", waiting_min=10), req("long", waiting_min=240)]) == ["long", "short"]
    assert order([req("late", start_h=11), req("early", start_h=9)]) == ["early", "late"]


def test_critical_beats_low_even_with_lost_and_waiting():
    assert order([req("low", "LOW", lost_appointment=True, waiting_min=300), req("crit", "CRITICAL")]) == ["crit", "low"]


def test_exact_tie_is_flagged_for_a_human_and_weights_are_tunable():
    ranked = rank_requests([req("a"), req("b")], now=NOW)
    assert ranked[0].tie_with_next and any("human" in r for r in ranked[0].reasons) and not ranked[1].tie_with_next
    assert order([req("p", "HIGH"), req("n", "NORMAL", waiting_min=600)], {"priority": 1, "waiting": 100}) == ["n", "p"]
    fixed = rank_requests([req("u1", is_unloading=True), req("u2", is_unloading=True)], now=NOW)
    assert not any(r.tie_with_next for r in fixed) and fixed[0].reasons[0].startswith("Already unloading")


def test_ranking_reasons_describe_the_decision():
    r = rank_requests([req("x", "HIGH", lost_appointment=True, waiting_min=45)], now=NOW)[0]
    assert r.reasons == ["HIGH priority", "current appointment is lost", "waiting 45 min"]
