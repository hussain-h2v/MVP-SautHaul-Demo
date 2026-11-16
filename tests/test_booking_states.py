from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from setuhaul import db as db_mod, tools
from setuhaul.clock import SimClock

SOURCE_DB = ROOT / "data" / "setuhaul_freight_operations.db"
TEST_DB = ROOT / "data" / "_booking_states_test.db"


@pytest.fixture
def temp_db():
    shutil.copyfile(SOURCE_DB, TEST_DB)
    try:
        yield db_mod.connect(TEST_DB)
    finally:
        TEST_DB.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(TEST_DB) + suffix).unlink(missing_ok=True)


def test_hold_expires_at_configured_ttl(temp_db):
    clock = SimClock("2026-08-04T09:00:00+05:30")
    options = tools.find_feasible_slots(
        temp_db,
        clock,
        shipment_id="SHP1021",
        after_ts=clock.now_ts(),
    )
    assert options

    held = tools.hold_slot(
        temp_db,
        clock,
        shipment_id="SHP1021",
        slot_id=options[0].slot_id,
        booking_source="DRIVER_CHAT",
    )
    assert held.ok

    clock.advance(tools.HOLD_TTL_MINUTES)
    assert tools.expire_stale_holds(temp_db, clock) == [held.appointment_id]
    appointment = temp_db.execute(
        "SELECT appointment_status, is_current FROM appointments WHERE appointment_id = ?",
        (held.appointment_id,),
    ).fetchone()
    assert appointment["appointment_status"] == "CANCELLED"
    assert appointment["is_current"] == 0
