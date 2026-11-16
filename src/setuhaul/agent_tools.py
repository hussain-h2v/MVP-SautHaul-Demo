from __future__ import annotations

import sqlite3
from typing import Any

from .clock import SimClock
from .db import audit
from .tools import (
    HOLD_TTL_MINUTES,
    confirm_appointment,
    expire_stale_holds,
    find_feasible_slots,
    get_shipment_snapshot,
    hold_slot,
    list_open_escalations,
    release_appointment,
    escalate,
)


def get_driver_context(conn: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    thread = conn.execute(
        "SELECT driver_id, shipment_id FROM chat_threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if thread is None:
        return {"ok": False, "error": "THREAD_NOT_FOUND"}

    driver_id = thread["driver_id"]
    active_shipments = conn.execute(
        """
        SELECT shipment_id, destination_facility_id, current_status, customer_name, priority_code
        FROM shipments
        WHERE driver_id = ?
          AND current_status IN ('PLANNED', 'ASSIGNED', 'IN_TRANSIT', 'AT_GATE', 'WAITING', 'IN_DOCK')
        ORDER BY original_eta_ts
        """,
        (driver_id,),
    ).fetchall()

    appointment = conn.execute(
        """
        SELECT a.appointment_id, a.slot_id, a.appointment_status, s.slot_start_ts, s.slot_end_ts, d.dock_code
        FROM appointments a
        LEFT JOIN appointment_slots s ON s.slot_id = a.slot_id
        LEFT JOIN docks d ON d.dock_id = s.dock_id
        WHERE a.shipment_id = ? AND a.is_current = 1
        ORDER BY a.booked_at DESC
        LIMIT 1
        """,
        (thread["shipment_id"],),
    ).fetchone() if thread["shipment_id"] else None

    return {
        "ok": True,
        "thread_id": thread_id,
        "driver_id": driver_id,
        "shipment_id": thread["shipment_id"],
        "active_shipments": [dict(row) for row in active_shipments],
        "current_appointment": dict(appointment) if appointment else None,
    }


def update_eta(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, eta: str, source: str, confidence: str) -> dict[str, Any]:
    try:
        eta_id = conn.execute(
            """
            INSERT INTO eta_updates (eta_update_id, shipment_id, source_type, declared_eta_ts,
                confidence_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"ETA-{abs(hash((shipment_id, eta, source, confidence))) % 10000000:08d}",
                shipment_id,
                source,
                eta,
                confidence,
                clock.now_ts(),
            ),
        )
        conn.execute(
            "UPDATE shipments SET latest_eta_ts = ?, updated_at = ? WHERE shipment_id = ?",
            (eta, clock.now_ts(), shipment_id),
        )
        return {"ok": True, "eta_update_id": eta_id.lastrowid, "shipment_id": shipment_id, "eta": eta}
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return {"ok": False, "error": str(exc)}


def find_feasible_slots_agent(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, earliest: str, latest: str | None = None, limit: int = 3) -> dict[str, Any]:
    options = find_feasible_slots(
        conn,
        clock,
        shipment_id=shipment_id,
        after_ts=earliest,
        latest_acceptable_ts=latest,
        max_results=limit,
    )
    return {
        "ok": True,
        "shipment_id": shipment_id,
        "options": [
            {
                "slot_id": item.slot_id,
                "dock_code": item.dock_code,
                "dock_type": item.dock_type,
                "slot_start_ts": item.slot_start_ts,
                "slot_end_ts": item.slot_end_ts,
                "requires_manual_approval": item.requires_manual_approval,
                "reason_if_flagged": item.reason_if_flagged,
            }
            for item in options
        ],
    }


def hold_slot_agent(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, slot_id: str, request_id: str, thread_id: str | None = None) -> dict[str, Any]:
    expire_stale_holds(conn, clock)
    result = hold_slot(
        conn,
        clock,
        shipment_id=shipment_id,
        slot_id=slot_id,
        booking_source="DRIVER_CHAT",
        thread_id=thread_id,
    )
    if not result.ok:
        return {"ok": False, "state": "unavailable", "reason": result.reason or "SLOT_TAKEN", "alternatives": find_feasible_slots_agent(conn, clock, shipment_id, clock.now_ts(), limit=3)["options"]}
    return {"ok": True, "state": "held", "appointment_id": result.appointment_id, "request_id": request_id}


def confirm_booking(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, slot_id: str, request_id: str) -> dict[str, Any]:
    appointment = conn.execute(
        "SELECT appointment_id FROM appointments WHERE shipment_id = ? AND slot_id = ? AND appointment_status = 'PENDING_CONFIRMATION' ORDER BY booked_at DESC LIMIT 1",
        (shipment_id, slot_id),
    ).fetchone()
    if appointment is None:
        return {"ok": False, "state": "unavailable", "reason": "NO_ACTIVE_HOLD"}
    confirm_appointment(conn, clock, appointment_id=appointment["appointment_id"])
    return {"ok": True, "state": "confirmed", "appointment_id": appointment["appointment_id"], "request_id": request_id}


def release_hold(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, slot_id: str) -> dict[str, Any]:
    appointment = conn.execute(
        "SELECT appointment_id FROM appointments WHERE shipment_id = ? AND slot_id = ? AND appointment_status = 'PENDING_CONFIRMATION' ORDER BY booked_at DESC LIMIT 1",
        (shipment_id, slot_id),
    ).fetchone()
    if appointment is None:
        return {"ok": False, "reason": "NO_ACTIVE_HOLD"}
    release_appointment(conn, clock, appointment_id=appointment["appointment_id"], reason="DRIVER_DECLINED")
    return {"ok": True, "state": "released"}


def escalate_to_human(conn: sqlite3.Connection, clock: SimClock, shipment_id: str, reason: str, context: str | None = None) -> dict[str, Any]:
    thread = conn.execute("SELECT thread_id, driver_id FROM chat_threads WHERE shipment_id = ? ORDER BY opened_at DESC LIMIT 1", (shipment_id,)).fetchone()
    if thread is None:
        return {"ok": False, "error": "NO_THREAD_FOR_SHIPMENT"}
    record = escalate(
        conn,
        clock,
        thread_id=thread["thread_id"],
        driver_id=thread["driver_id"],
        shipment_id=shipment_id,
        trigger="MANUAL_REVIEW",
        summary=reason,
        recommended_action=context or "Manual coordinator review required.",
    )
    return {
        "ok": True,
        "state": "escalated",
        "exception_id": record.exception_id,
        "shipment_id": shipment_id,
        "reason": reason,
    }


def list_open_escalations_agent(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return list_open_escalations(conn)
