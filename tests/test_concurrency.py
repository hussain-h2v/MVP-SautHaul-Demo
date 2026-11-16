"""Integrity proof: two drivers race for the same slot.

This is deliverable #5. It opens two independent connections to the same
database (simulating two simultaneous conversations), and makes both try to
hold the exact same open slot at the same instant using a thread barrier so
neither gets a head start. It then asserts:

  1. Exactly one of the two calls succeeded.
  2. The database has exactly one active (PENDING_CONFIRMATION / CONFIRMED /
     IN_PROGRESS) appointment for that slot -- never zero, never two.
  3. The loser got a clean, reportable failure, not a crash or a silent
     overwrite.

Run with:  python -m tests.test_concurrency
"""

from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from setuhaul import db as db_mod   # noqa: E402
from setuhaul import tools          # noqa: E402
from setuhaul.clock import SimClock  # noqa: E402

SOURCE_DB = ROOT / "data" / "setuhaul_freight_operations.db"
TEST_DB = ROOT / "data" / "_concurrency_test.db"


def pick_open_slot_and_shipments(conn) -> tuple[str, str, str]:
    """An OPEN, unoccupied standard slot at Jaipur, and two NORMAL/standard
    shipments that are both allowed to use it, so the race is fair."""
    slot = conn.execute(
        "SELECT slot_id FROM v_slot_availability "
        "WHERE facility_id = 'FAC-JAI-01' AND dock_type = 'STANDARD' "
        "AND availability_status = 'AVAILABLE' ORDER BY slot_start_ts LIMIT 1"
    ).fetchone()
    shp_a = "SHP1017"  # LOW priority, standard, unassigned slot pending
    shp_b = "SHP1013"  # NORMAL priority, standard
    return slot["slot_id"], shp_a, shp_b


def run_race(n_trials: int = 5) -> None:
    shutil.copyfile(SOURCE_DB, TEST_DB)
    results = {"ok": 0, "fail": 0}

    for trial in range(n_trials):
        setup_conn = db_mod.connect(TEST_DB)
        slot_id, shp_a, shp_b = pick_open_slot_and_shipments(setup_conn)
        setup_conn.close()

        outcomes: dict[str, tools.HoldResult] = {}
        barrier = threading.Barrier(2)

        def attempt(shipment_id: str, key: str) -> None:
            conn = db_mod.connect(TEST_DB)
            clock = SimClock("2026-08-04T09:00:00+05:30")
            barrier.wait()  # force both threads to call hold_slot at the same instant
            outcomes[key] = tools.hold_slot(
                conn, clock, shipment_id=shipment_id, slot_id=slot_id,
                booking_source="DRIVER_CHAT",
            )
            conn.close()

        t1 = threading.Thread(target=attempt, args=(shp_a, "A"))
        t2 = threading.Thread(target=attempt, args=(shp_b, "B"))
        t1.start(); t2.start()
        t1.join(); t2.join()

        successes = [k for k, v in outcomes.items() if v.ok]
        failures = [k for k, v in outcomes.items() if not v.ok]
        assert len(successes) == 1, f"Trial {trial}: expected exactly 1 success, got {successes}"
        assert len(failures) == 1, f"Trial {trial}: expected exactly 1 failure, got {failures}"
        assert outcomes[failures[0]].reason == "SLOT_TAKEN"

        check_conn = db_mod.connect(TEST_DB)
        count = check_conn.execute(
            "SELECT COUNT(*) AS c FROM appointments WHERE slot_id = ? "
            "AND appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')",
            (slot_id,),
        ).fetchone()["c"]
        assert count == 1, f"Trial {trial}: expected exactly 1 active appointment on {slot_id}, found {count}"
        check_conn.close()

        print(f"Trial {trial}: slot={slot_id} winner={successes[0]} loser={failures[0]} "
              f"(reason={outcomes[failures[0]].reason}) -- active appointments on slot: {count}  OK")
        results["ok"] += 1

    TEST_DB.unlink(missing_ok=True)
    for ext in ("-wal", "-shm"):
        Path(str(TEST_DB) + ext).unlink(missing_ok=True)
    print(f"\n{results['ok']}/{n_trials} trials confirmed: no double booking, ever.")


if __name__ == "__main__":
    run_race()
