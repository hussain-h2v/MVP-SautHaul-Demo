"""Business tools: structured, deterministic reads and writes.

Nothing in this file reads free text and nothing in it is a language model.
It is the "business tools" + "scheduling logic" + "database" layers from the
project brief's table: read shipments, calculate feasibility, hold/confirm/
release capacity, escalate -- all plain code against the SQLite system of
record. The conversation layer (conversation.py) is the only caller that
ever sees driver text; it calls these functions with already-structured
arguments.

Concurrency: a hold is a real row in `appointments` with status
PENDING_CONFIRMATION, written inside a BEGIN IMMEDIATE transaction. The
database's own partial unique index (ux_active_appointment_per_slot) is the
single source of truth for "only one active booking per slot" -- we do not
re-implement that rule in Python, we just handle the IntegrityError it
raises when a second writer loses the race.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .clock import SimClock
from .db import audit

HOLD_TTL_MINUTES = 5
PRIORITY_WEIGHT = {"CRITICAL": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1}

ACTIVE_SHIPMENT_STATUSES = (
    "PLANNED", "ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK",
)
ACTIVE_APPOINTMENT_STATUSES = ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def find_driver_active_shipments(conn: sqlite3.Connection, driver_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT shipment_id, destination_facility_id, current_status,
               customer_name, priority_code, original_eta_ts
        FROM shipments
        WHERE driver_id = ?
          AND current_status IN ({','.join('?' * len(ACTIVE_SHIPMENT_STATUSES))})
        ORDER BY original_eta_ts
        """,
        (driver_id, *ACTIVE_SHIPMENT_STATUSES),
    ).fetchall()


def get_shipment_snapshot(conn: sqlite3.Connection, shipment_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM v_inbound_operational_state WHERE shipment_id = ?",
        (shipment_id,),
    ).fetchone()
    if row is None:
        return None
    shipment = conn.execute(
        "SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,)
    ).fetchone()
    facility = conn.execute(
        "SELECT * FROM facilities WHERE facility_id = ?",
        (shipment["destination_facility_id"],),
    ).fetchone()
    return {**dict(row), "shipment": dict(shipment), "facility": dict(facility)}


def get_facility_rule(conn: sqlite3.Connection, facility_id: str, rule_type: str) -> Optional[str]:
    row = conn.execute(
        "SELECT rule_value FROM facility_rules "
        "WHERE facility_id = ? AND rule_type = ? AND active_flag = 1",
        (facility_id, rule_type),
    ).fetchone()
    return row["rule_value"] if row else None


# --------------------------------------------------------------------------
# ETA
# --------------------------------------------------------------------------

def record_eta_update(
    conn: sqlite3.Connection, clock: SimClock, *, shipment_id: str, declared_eta_ts: str,
    source_type: str, confidence_code: str, delay_reason_code: Optional[str],
    reported_by_driver_id: Optional[str], note: str,
) -> str:
    eta_id = new_id("ETA")
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """
            INSERT INTO eta_updates (eta_update_id, shipment_id, source_type,
                reported_by_driver_id, declared_eta_ts, confidence_code,
                delay_reason_code, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eta_id, shipment_id, source_type, reported_by_driver_id, declared_eta_ts,
             confidence_code, delay_reason_code, note, clock.now_ts()),
        )
        conn.execute(
            "UPDATE shipments SET latest_eta_ts = ?, updated_at = ? WHERE shipment_id = ?",
            (declared_eta_ts, clock.now_ts(), shipment_id),
        )
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    return eta_id


# --------------------------------------------------------------------------
# Feasibility (the "scheduling logic" layer)
# --------------------------------------------------------------------------

@dataclass
class SlotOption:
    slot_id: str
    dock_code: str
    dock_type: str
    slot_start_ts: str
    slot_end_ts: str
    requires_manual_approval: bool = False
    reason_if_flagged: str = ""


def _dock_compatible(required_dock_type: str, temp_required: bool, load_weight_kg: int,
                      dock_type: str, supports_refrigerated: int, max_weight_kg: int) -> bool:
    if load_weight_kg > max_weight_kg:
        return False
    if temp_required and not supports_refrigerated:
        return False
    if required_dock_type == "ANY":
        return True
    return required_dock_type == dock_type


def find_feasible_slots(
    conn: sqlite3.Connection, clock: SimClock, *, shipment_id: str, after_ts: str,
    latest_acceptable_ts: Optional[str] = None, max_results: int = 3,
) -> list[SlotOption]:
    """Read-only. Showing an option here reserves nothing (see decision #6)."""
    expire_stale_holds(conn, clock)

    shipment = conn.execute(
        "SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,)
    ).fetchone()
    if shipment is None:
        return []
    facility = conn.execute(
        "SELECT * FROM facilities WHERE facility_id = ?",
        (shipment["destination_facility_id"],),
    ).fetchone()

    last_new_start = get_facility_rule(conn, facility["facility_id"], "LAST_NEW_START_TIME")

    rows = conn.execute(
        """
        SELECT * FROM v_slot_availability
        WHERE facility_id = ?
          AND availability_status = 'AVAILABLE'
          AND slot_start_ts >= ?
        ORDER BY slot_start_ts, dock_code
        """,
        (shipment["destination_facility_id"], after_ts),
    ).fetchall()

    options: list[SlotOption] = []
    for r in rows:
        if not _dock_compatible(
            shipment["required_dock_type"], bool(shipment["temperature_control_required"]),
            shipment["load_weight_kg"], r["dock_type"], r["supports_refrigerated"],
            r["max_vehicle_weight_kg"],
        ):
            continue
        if latest_acceptable_ts and r["slot_start_ts"] > latest_acceptable_ts:
            continue
        # The job must plausibly finish before the facility closes.
        close_dt = SimClock.parse(r["slot_start_ts"][:10] + "T" + facility["close_time"] + ":00+05:30")
        slot_start_dt = SimClock.parse(r["slot_start_ts"])
        from datetime import timedelta
        if slot_start_dt + timedelta(minutes=shipment["expected_unload_min"]) > close_dt:
            continue

        requires_approval = False
        reason = ""
        if last_new_start:
            start_hhmm = r["slot_start_ts"][11:16]
            if start_hhmm >= last_new_start:
                requires_approval = True
                reason = (
                    f"This slot starts at or after the facility's {last_new_start} cutoff; "
                    "manager approval is required."
                )

        options.append(SlotOption(
            slot_id=r["slot_id"], dock_code=r["dock_code"], dock_type=r["dock_type"],
            slot_start_ts=r["slot_start_ts"], slot_end_ts=r["slot_end_ts"],
            requires_manual_approval=requires_approval, reason_if_flagged=reason,
        ))
        if len(options) >= max_results:
            break
    return options


def recheck_slot_available(conn: sqlite3.Connection, clock: SimClock, slot_id: str) -> bool:
    expire_stale_holds(conn, clock)
    row = conn.execute(
        "SELECT availability_status FROM v_slot_availability WHERE slot_id = ?",
        (slot_id,),
    ).fetchone()
    return row is not None and row["availability_status"] == "AVAILABLE"


# --------------------------------------------------------------------------
# Commitment: hold / confirm / release (the "capacity layer")
# --------------------------------------------------------------------------

@dataclass
class HoldResult:
    ok: bool
    appointment_id: Optional[str] = None
    reason: Optional[str] = None


def hold_slot(
    conn: sqlite3.Connection, clock: SimClock, *, shipment_id: str, slot_id: str,
    booking_source: str, thread_id: Optional[str] = None,
) -> HoldResult:
    """Write a PENDING_CONFIRMATION appointment. Atomic: either this writer
    gets the slot or it gets a clean, reportable failure -- never a silent
    double allocation. Any prior active appointment for this shipment is
    superseded (cancelled, linked via replaced_appointment_id) in the same
    transaction, so a shipment never ends up holding two active slots.
    """
    expire_stale_holds(conn, clock)
    appointment_id = new_id("APT")
    now = clock.now_ts()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        prior = conn.execute(
            f"""
            SELECT appointment_id FROM appointments
            WHERE shipment_id = ? AND is_current = 1
              AND appointment_status IN ({','.join('?' * len(ACTIVE_APPOINTMENT_STATUSES))})
            """,
            (shipment_id, *ACTIVE_APPOINTMENT_STATUSES),
        ).fetchone()
        if prior:
            conn.execute(
                "UPDATE appointments SET appointment_status = 'CANCELLED', is_current = 0, "
                "cancelled_at = ?, cancellation_reason = 'SUPERSEDED_BY_NEW_HOLD', updated_at = ? "
                "WHERE appointment_id = ?",
                (now, now, prior["appointment_id"]),
            )

        conn.execute(
            """
            INSERT INTO appointments (appointment_id, shipment_id, slot_id, appointment_status,
                booking_source, is_current, booked_at, replaced_appointment_id, updated_at)
            VALUES (?, ?, ?, 'PENDING_CONFIRMATION', ?, 1, ?, ?, ?)
            """,
            (appointment_id, shipment_id, slot_id, booking_source, now,
             prior["appointment_id"] if prior else None, now),
        )
        expires_at = clock.format(clock.now() + __import__("datetime").timedelta(minutes=HOLD_TTL_MINUTES))
        conn.execute(
            "INSERT INTO agent_holds (appointment_id, expires_at, created_at) VALUES (?, ?, ?)",
            (appointment_id, expires_at, now),
        )
        audit(conn, now, "HOLD", f"slot={slot_id} source={booking_source}", thread_id, shipment_id)
        conn.commit()
        return HoldResult(ok=True, appointment_id=appointment_id)
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK;")
        return HoldResult(ok=False, reason="SLOT_TAKEN")


def confirm_appointment(conn: sqlite3.Connection, clock: SimClock, *, appointment_id: str,
                         thread_id: Optional[str] = None) -> None:
    now = clock.now_ts()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            "UPDATE appointments SET appointment_status = 'CONFIRMED', confirmed_at = ?, "
            "warehouse_confirmation_ref = ?, updated_at = ? WHERE appointment_id = ?",
            (now, new_id("WHC"), now, appointment_id),
        )
        conn.execute("DELETE FROM agent_holds WHERE appointment_id = ?", (appointment_id,))
        row = conn.execute(
            "SELECT shipment_id FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
        om_id = new_id("OM")
        conn.execute(
            """
            INSERT INTO operational_messages (operational_message_id, shipment_id, appointment_id,
                channel, sender_address, recipient_address, subject, message_body, sent_at,
                delivery_status)
            VALUES (?, ?, ?, 'INTERNAL', 'dispatch-agent@setuhaul.internal',
                    'warehouse-planner@setuhaul.internal', 'Slot confirmed',
                    'Appointment ' || ? || ' confirmed.', ?, 'DELIVERED')
            """,
            (om_id, row["shipment_id"], appointment_id, appointment_id, now),
        )
        audit(conn, now, "CONFIRM", f"appointment={appointment_id}", thread_id, row["shipment_id"])
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def release_appointment(conn: sqlite3.Connection, clock: SimClock, *, appointment_id: str,
                         reason: str, thread_id: Optional[str] = None) -> None:
    now = clock.now_ts()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        row = conn.execute(
            "SELECT shipment_id FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
        conn.execute(
            "UPDATE appointments SET appointment_status = 'CANCELLED', is_current = 0, "
            "cancelled_at = ?, cancellation_reason = ?, updated_at = ? WHERE appointment_id = ?",
            (now, reason, now, appointment_id),
        )
        conn.execute("DELETE FROM agent_holds WHERE appointment_id = ?", (appointment_id,))
        audit(conn, now, "RELEASE", f"appointment={appointment_id} reason={reason}",
              thread_id, row["shipment_id"] if row else None)
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def expire_stale_holds(conn: sqlite3.Connection, clock: SimClock) -> list[str]:
    now = clock.now_ts()
    stale = conn.execute(
        "SELECT appointment_id FROM agent_holds WHERE expires_at <= ?", (now,)
    ).fetchall()
    expired = []
    for row in stale:
        release_appointment(conn, clock, appointment_id=row["appointment_id"], reason="HOLD_EXPIRED")
        expired.append(row["appointment_id"])
    return expired


# --------------------------------------------------------------------------
# Priority policy (used both to rank suggestions and, in the scheduler
# tool, to decide dispatch order -- never to decide who "wins" a slot;
# the unique index always decides that).
# --------------------------------------------------------------------------

def priority_rank_key(priority_code: str, requested_at: str) -> tuple:
    return (-PRIORITY_WEIGHT.get(priority_code, 0), requested_at)


# --------------------------------------------------------------------------
# Escalation (hand-off to a human; decisions #10 and #12)
# --------------------------------------------------------------------------

@dataclass
class HandoffRecord:
    exception_id: str
    shipment_id: Optional[str]
    driver_id: str
    thread_id: str
    trigger: str
    summary: str
    recommended_action: str


def escalate(
    conn: sqlite3.Connection, clock: SimClock, *, thread_id: str, driver_id: str,
    shipment_id: Optional[str], trigger: str, summary: str, recommended_action: str,
) -> HandoffRecord:
    now = clock.now_ts()
    exception_id = new_id("EXC")
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """
            INSERT INTO driver_exceptions (exception_id, shipment_id, driver_id, thread_id,
                exception_type, reported_at, severity_code, exception_status, description)
            VALUES (?, ?, ?, ?, 'UNKNOWN', ?, 'HIGH', 'ESCALATED', ?)
            """,
            (exception_id, shipment_id, driver_id, thread_id, now, summary),
        )
        conn.execute(
            "UPDATE chat_threads SET thread_status = 'ESCALATED' WHERE thread_id = ?",
            (thread_id,),
        )
        om_id = new_id("OM")
        conn.execute(
            """
            INSERT INTO operational_messages (operational_message_id, shipment_id, appointment_id,
                channel, sender_address, recipient_address, subject, message_body, sent_at,
                delivery_status)
            VALUES (?, ?, NULL, 'INTERNAL', 'dispatch-agent@setuhaul.internal',
                    'ops-coordinator@setuhaul.internal', ?, ?, ?, 'SENT')
            """,
            (om_id, shipment_id or "UNKNOWN", f"Escalation: {trigger}",
             f"{summary}\nRecommended action: {recommended_action}", now),
        )
        audit(conn, now, "ESCALATE", f"trigger={trigger} summary={summary}", thread_id, shipment_id)
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    return HandoffRecord(
        exception_id=exception_id, shipment_id=shipment_id, driver_id=driver_id,
        thread_id=thread_id, trigger=trigger, summary=summary,
        recommended_action=recommended_action,
    )


# --------------------------------------------------------------------------
# Coordinator queue (reads for the human side of "a person approves or
# takes over" -- the boundary the brief draws; see Boundaries table).
# --------------------------------------------------------------------------

def list_open_escalations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.exception_id, e.thread_id, e.driver_id, e.shipment_id, e.reported_at,
               e.severity_code, e.description, s.customer_name, s.priority_code
        FROM driver_exceptions e
        LEFT JOIN shipments s ON s.shipment_id = e.shipment_id
        WHERE e.exception_status = 'ESCALATED'
        ORDER BY e.reported_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_pending_approvals(conn: sqlite3.Connection, clock: SimClock) -> list[dict]:
    """Appointments our own conversation layer held but did not auto-confirm,
    because the slot needs a human sign-off (e.g. the facility's last-new-
    start rule). Anything here is a live hold, not yet a commitment."""
    expire_stale_holds(conn, clock)
    rows = conn.execute(
        """
        SELECT a.appointment_id, a.shipment_id, a.booked_at, h.expires_at,
               sl.slot_start_ts, sl.slot_end_ts, d.dock_code, d.dock_type,
               s.customer_name, s.priority_code, s.driver_id
        FROM appointments a
        JOIN appointment_slots sl ON sl.slot_id = a.slot_id
        JOIN docks d ON d.dock_id = sl.dock_id
        JOIN shipments s ON s.shipment_id = a.shipment_id
        LEFT JOIN agent_holds h ON h.appointment_id = a.appointment_id
        WHERE a.appointment_status = 'PENDING_CONFIRMATION' AND a.booking_source = 'DRIVER_CHAT'
        ORDER BY a.booked_at
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_audit_log(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT log_id, ts, thread_id, shipment_id, action, detail FROM agent_audit_log "
        "ORDER BY log_id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Coordinator actions: the only two writes a human, not the agent, may make
# on a held appointment. Both resolve the escalation that asked for them.
# --------------------------------------------------------------------------

def approve_held_appointment(conn: sqlite3.Connection, clock: SimClock, *, appointment_id: str) -> dict:
    row = conn.execute(
        "SELECT shipment_id FROM appointments WHERE appointment_id = ?", (appointment_id,)
    ).fetchone()
    if row is None:
        return {"ok": False, "reason": "APPOINTMENT_NOT_FOUND"}
    confirm_appointment(conn, clock, appointment_id=appointment_id)
    conn.execute(
        "UPDATE driver_exceptions SET exception_status = 'RESOLVED' "
        "WHERE shipment_id = ? AND exception_status = 'ESCALATED'",
        (row["shipment_id"],),
    )
    audit(conn, clock.now_ts(), "COORDINATOR_APPROVE", f"appointment={appointment_id}",
          None, row["shipment_id"])
    return {"ok": True}


def reject_held_appointment(conn: sqlite3.Connection, clock: SimClock, *, appointment_id: str,
                             reason: str) -> dict:
    row = conn.execute(
        "SELECT shipment_id FROM appointments WHERE appointment_id = ?", (appointment_id,)
    ).fetchone()
    if row is None:
        return {"ok": False, "reason": "APPOINTMENT_NOT_FOUND"}
    release_appointment(conn, clock, appointment_id=appointment_id,
                         reason=f"REJECTED_BY_COORDINATOR: {reason}")
    conn.execute(
        "UPDATE driver_exceptions SET exception_status = 'RESOLVED' "
        "WHERE shipment_id = ? AND exception_status = 'ESCALATED'",
        (row["shipment_id"],),
    )
    audit(conn, clock.now_ts(), "COORDINATOR_REJECT", f"appointment={appointment_id} reason={reason}",
          None, row["shipment_id"])
    return {"ok": True}
