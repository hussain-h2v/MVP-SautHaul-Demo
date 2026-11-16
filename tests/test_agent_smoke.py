from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from setuhaul import ScriptedAgent
from setuhaul import db as db_mod
from setuhaul.clock import SimClock

SOURCE_DB = ROOT / "data" / "setuhaul_freight_operations.db"
TEST_DB = ROOT / "data" / "_agent_smoke.db"


@pytest.fixture
def temp_db():
    shutil.copyfile(SOURCE_DB, TEST_DB)
    try:
        yield db_mod.connect(TEST_DB)
    finally:
        TEST_DB.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(TEST_DB) + suffix).unlink(missing_ok=True)


def test_scripted_agent_handles_single_shipments(temp_db):
    conn = temp_db
    agent = ScriptedAgent(conn, SimClock("2026-08-04T09:00:00+05:30"))
    response = agent.run("THR001", "hi")
    assert isinstance(response, str)
    assert "I couldn't tell" in response


def test_scripted_agent_safe_run_handles_missing_thread(temp_db):
    conn = temp_db
    agent = ScriptedAgent(conn, SimClock("2026-08-04T09:00:00+05:30"))
    result = agent.safe_run("NO_SUCH_THREAD", "hi")
    assert result["ok"] is False
    assert "error" in result


def test_scripted_agent_keeps_ambiguous_shipment_flow_in_english(temp_db):
    agent = ScriptedAgent(temp_db, SimClock("2026-08-04T09:00:00+05:30"))

    clarification = agent.run("THR010", "hi")
    assert "more than one active shipment" in clarification
    assert "Which shipment" in clarification

    resolved = agent.run("THR010", "SHP1004")
    assert resolved.startswith("Okay, SHP1004.")

    options = agent.run("THR010", "I will reach by 15:00")
    assert options.startswith("These slots are available")


@pytest.mark.parametrize("selection", ["book Dock D3", "book slot dock d3 for me"])
def test_scripted_agent_books_the_named_dock_from_offered_options(temp_db, selection):
    conversation_states = {}
    clock = SimClock("2026-08-04T09:00:00+05:30")
    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)

    options = agent.run("THR007", "I will be reaching at 17:00 to Dock D3")
    assert "Dock D3 (Standard) -- 17:00 to 18:00" in options

    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    booked = agent.run("THR007", selection)
    assert booked.startswith("Booked. Dock D3, 17:00 to 18:00.")

    appointment_id = booked.rsplit("Appointment reference ", 1)[1].rstrip(".")
    dock = temp_db.execute(
        """
        SELECT d.dock_code
        FROM appointments a
        JOIN appointment_slots s ON s.slot_id = a.slot_id
        JOIN docks d ON d.dock_id = s.dock_id
        WHERE a.appointment_id = ?
        """,
        (appointment_id,),
    ).fetchone()
    assert dock["dock_code"] == "D3"


def test_scripted_agent_does_not_default_unoffered_dock_to_first_option(temp_db):
    conversation_states = {}
    clock = SimClock("2026-08-04T09:00:00+05:30")
    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    agent.run("THR007", "I will be reaching at 17:00 to Dock D3")

    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    response = agent.run("THR007", "book Dock D99")
    assert "I didn't offer dock D99" in response

    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    booked = agent.run("THR007", "book Dock D3")
    assert booked.startswith("Booked. Dock D3, 17:00 to 18:00.")


def test_scripted_agent_books_numbered_option_after_agent_recreation(temp_db):
    conversation_states = {}
    clock = SimClock("2026-08-04T09:00:00+05:30")
    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    options = agent.run("THR007", "I will be reaching at 17:00 to Dock D3")
    third_option = re.search(r"^3\) Dock ([A-Z]\d+)", options, re.MULTILINE)
    assert third_option is not None

    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    invalid_choice = agent.run("THR007", "99")
    assert "I offered 3 options" in invalid_choice

    agent = ScriptedAgent(temp_db, clock, conversation_states=conversation_states)
    booked = agent.run("THR007", "3")
    assert booked.startswith(f"Booked. Dock {third_option.group(1)}, ")
