from __future__ import annotations

import shutil
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from setuhaul import db as db_mod
from setuhaul.clock import SimClock
from setuhaul.scheduler_tool import DockMachine, Job, _priority_rule, propose_schedule

SOURCE_DB = ROOT / "data" / "setuhaul_freight_operations.db"
TEST_DB = ROOT / "data" / "_scheduler_test.db"
COMPETING_SHIPMENTS = ["SHP1002", "SHP1003", "SHP1004", "SHP1006"]


@pytest.fixture
def temp_db():
    shutil.copyfile(SOURCE_DB, TEST_DB)
    try:
        yield db_mod.connect(TEST_DB)
    finally:
        TEST_DB.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(TEST_DB) + suffix).unlink(missing_ok=True)


def test_competing_snapshot_keeps_in_progress_load_fixed(temp_db):
    before = temp_db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    result = propose_schedule(
        temp_db,
        SimClock("2026-08-04T09:00:00+05:30"),
        "FAC-JAI-01",
        shipment_ids=COMPETING_SHIPMENTS,
    )

    assert set(result["shipment_ids"]) == set(COMPETING_SHIPMENTS)
    assert result["fixed_in_progress"] == [
        {
            "shipment_id": "SHP1002",
            "dock": "D2",
            "estimated_finish": "2026-08-04T09:18:00+05:30",
            "rescheduled": False,
        }
    ]
    for schedule_key in ("priority_rule", "naive_fcfs"):
        entries = result[schedule_key]["entries"]
        assert {entry["shipment_id"] for entry in entries} == {
            "SHP1003",
            "SHP1004",
            "SHP1006",
        }
        assert all(entry["shipment_id"] != "SHP1002" for entry in entries)
        assert result[schedule_key]["priority_weighted_wait_min"] >= 0

    assert temp_db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == before


def test_priority_breaks_ties_after_earliest_feasible_start():
    as_of = SimClock.parse("2026-08-04T09:00:00+05:30")
    jobs = [
        Job("LOW", "LOW", as_of, 30, "STANDARD", False, 1000),
        Job("HIGH", "HIGH", as_of, 30, "STANDARD", False, 1000),
    ]
    dock = DockMachine("D1", "STANDARD", 0, 10000, as_of)

    schedule = _priority_rule(jobs, [dock], as_of)

    assert schedule[0].shipment_id == "HIGH"
    assert schedule[1].shipment_id == "LOW"
    assert schedule[1].start_ts - schedule[0].start_ts == timedelta(minutes=30)
