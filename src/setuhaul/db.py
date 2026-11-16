"""Connection helper and the small set of additive, app-owned tables.

We never alter the tables SetuHaul supplied (shipments, appointments,
appointment_slots, ...). Those stay the system of record exactly as
delivered, including its two partial-unique-index rules. We only add two
tables of our own, for state the supplied schema has no room for:

- agent_holds: the expiry time of a PENDING_CONFIRMATION appointment that
  exists only because our agent offered it to a driver. The supplied schema
  has no TTL concept; a hold that nobody confirms must still get released.
- agent_audit_log: an append-only trail of every decision the agent made
  (hold, confirm, release, escalate) with the reason, so an escalation can
  hand a human a complete record instead of a guess.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "setuhaul_freight_operations.db"


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    _ensure_app_tables(conn)
    return conn


def _ensure_app_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_holds (
            appointment_id TEXT PRIMARY KEY
                REFERENCES appointments(appointment_id),
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            thread_id TEXT,
            shipment_id TEXT,
            action TEXT NOT NULL,
            detail TEXT NOT NULL
        );
        """
    )


def audit(conn: sqlite3.Connection, ts: str, action: str, detail: str,
          thread_id: str | None = None, shipment_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO agent_audit_log (ts, thread_id, shipment_id, action, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, thread_id, shipment_id, action, detail),
    )
