from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from setuhaul import ScriptedAgent
from setuhaul.clock import SimClock
from setuhaul.db import connect
from setuhaul.tools import list_audit_log, list_open_escalations

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data" / "setuhaul_freight_operations.db"
SIM_TS = "2026-08-04T09:00:00+05:30"


def get_conn():
    return connect(DB_PATH)


def get_clock():
    return SimClock(SIM_TS)


def send_driver_message(thread_id: str, text: str) -> str:
    conn = get_conn()
    try:
        agent = ScriptedAgent(
            conn,
            get_clock(),
            conversation_states=st.session_state.setdefault("conversation_thread_states", {}),
        )
        return agent.run(thread_id, text)
    finally:
        conn.close()


def fetch_threads(conn):
    return conn.execute(
        "SELECT thread_id, driver_id, shipment_id, thread_status, opened_at FROM chat_threads ORDER BY opened_at"
    ).fetchall()


def fetch_messages(conn, thread_id: str):
    return conn.execute(
        "SELECT sender_type, message_text, message_ts FROM chat_messages WHERE thread_id = ? ORDER BY message_ts",
        (thread_id,),
    ).fetchall()


def render_dock_board(conn, facility_id: str):
    slot_rows = conn.execute(
        """
        SELECT s.slot_id, s.slot_start_ts, s.slot_end_ts, s.dock_code, s.dock_type,
               s.availability_status, s.appointment_status, s.shipment_id
        FROM v_slot_availability s
        WHERE s.facility_id = ?
        ORDER BY s.slot_start_ts, s.dock_code
        """,
        (facility_id,),
    ).fetchall()

    if not slot_rows:
        st.info("No slot data for this facility.")
        return

    slot_times = sorted({row["slot_start_ts"][11:16] for row in slot_rows})
    dock_labels = sorted({f"{row['dock_code']} · {row['dock_type'].title()}" for row in slot_rows})
    board = {dock: {time: "—" for time in slot_times} for dock in dock_labels}

    for row in slot_rows:
        dock = f"{row['dock_code']} · {row['dock_type'].title()}"
        time = row["slot_start_ts"][11:16]
        if row["appointment_status"] == "PENDING_CONFIRMATION":
            status = "HELD"
        elif row["appointment_status"] in ("CONFIRMED", "IN_PROGRESS"):
            status = "CONFIRMED"
        elif row["availability_status"] == "BLOCKED":
            status = "BLOCKED"
        elif row["availability_status"] == "AVAILABLE":
            status = "OPEN"
        else:
            status = row["availability_status"].replace("_", " ")
        board[dock][time] = f"{status}\n{row['shipment_id']}" if row["shipment_id"] else status

    grid = pd.DataFrame.from_dict(board, orient="index", columns=slot_times)
    grid.index.name = "Dock"

    colors = {
        "OPEN": ("#E7F5EC", "#14532D"),
        "HELD": ("#FFF1D6", "#7C2D12"),
        "CONFIRMED": ("#E5EEFF", "#1E3A8A"),
        "BLOCKED": ("#FDE8E7", "#7F1D1D"),
    }

    def style_cell(value: str) -> str:
        status = value.split("\n", 1)[0]
        background, foreground = colors.get(status, ("#F1F5F9", "#334155"))
        return (
            f"background-color: {background}; color: {foreground}; "
            "font-weight: 600; text-align: center; white-space: pre-line;"
        )

    st.caption("Each column is a slot start time. Booked cells include the shipment ID.")
    st.dataframe(
        grid.style.map(style_cell),
        use_container_width=True,
        height=min(460, 45 + 42 * len(grid)),
    )
    st.markdown("**Legend:** 🟩 Open · 🟧 Held · 🟦 Confirmed · 🟥 Blocked")


def render_integrity_badge(conn) -> str:
    row = conn.execute(
        """
        SELECT COUNT(*) AS conflict_count
        FROM (
            SELECT slot_id
            FROM appointments
            WHERE appointment_status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'IN_PROGRESS')
            GROUP BY slot_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()
    count = row["conflict_count"] if row else 0
    return "PASS" if count == 0 else f"CONFLICTS={count}"


def main():
    st.set_page_config(page_title="SetuHaul Ops Console", layout="wide")
    conn = get_conn()
    clock = get_clock()

    st.title("SetuHaul Driver Chat + Operations Console")
    st.caption(f"Scenario time: {clock.now_ts()} (Asia/Kolkata)")

    left, right = st.columns([1.3, 1.7])

    with left:
        threads = fetch_threads(conn)
        thread_ids = [row["thread_id"] for row in threads]
        default_thread = st.session_state.get("selected_thread", thread_ids[0] if thread_ids else None)
        selected_thread = st.selectbox("Select driver thread", thread_ids, index=thread_ids.index(default_thread) if default_thread in thread_ids else 0)
        st.session_state["selected_thread"] = selected_thread

        thread_row = next((row for row in threads if row["thread_id"] == selected_thread), None)
        if thread_row is not None:
            st.write(f"Driver: {thread_row['driver_id']} | Shipment: {thread_row['shipment_id']} | Status: {thread_row['thread_status']}")

        quick_replies = [
            "Hi",
            "I am 20 minutes late",
            "Can I get a slot at 15:30?",
            "I need a different dock",
            "I will reach by 17:00",
            "Need human help",
        ]
        for label in quick_replies:
            if st.button(label, key=f"chip_{label}_{selected_thread}"):
                reply = send_driver_message(selected_thread, label)
                st.toast(f"Driver message sent: {label}")
                st.rerun()

        st.subheader("Chat transcript")
        for row in fetch_messages(conn, selected_thread):
            sender = row["sender_type"]
            msg = html.escape(row["message_text"])
            timestamp = html.escape(row["message_ts"])
            if sender == "DRIVER":
                st.html(
                    f"<div style='padding:10px 12px; border-radius:10px; "
                    f"background-color:#EAF2FF; color:#14233B; "
                    f"border:1px solid #A8C4F0; border-left:5px solid #2563EB; "
                    f"margin-bottom:8px; overflow-wrap:anywhere; white-space:pre-wrap'>"
                    f"<div style='font-size:0.75rem; font-weight:700; color:#1D4ED8'>"
                    f"DRIVER · {timestamp}</div><div>{msg}</div></div>"
                )
            else:
                st.html(
                    f"<div style='padding:10px 12px; border-radius:10px; "
                    f"background-color:#E9F8EF; color:#102A1B; "
                    f"border:1px solid #9FD5AF; border-left:5px solid #15803D; "
                    f"margin-bottom:8px; overflow-wrap:anywhere; white-space:pre-wrap'>"
                    f"<div style='font-size:0.75rem; font-weight:700; color:#166534'>"
                    f"AGENT · {timestamp}</div><div>{msg}</div></div>"
                )

        user_text = st.chat_input(
            "Type a driver message",
            key=f"driver_chat_input_{selected_thread}",
        )
        if user_text and user_text.strip():
            send_driver_message(selected_thread, user_text.strip())
            st.rerun()

    with right:
        facility_rows = conn.execute("SELECT facility_id, facility_name FROM facilities ORDER BY facility_name").fetchall()
        facility_ids = [row["facility_id"] for row in facility_rows]
        shipment_facility_id = None
        if thread_row is not None and thread_row["shipment_id"]:
            shipment_facility = conn.execute(
                "SELECT destination_facility_id FROM shipments WHERE shipment_id = ?",
                (thread_row["shipment_id"],),
            ).fetchone()
            if shipment_facility:
                shipment_facility_id = shipment_facility["destination_facility_id"]
        default_facility_id = (
            shipment_facility_id if shipment_facility_id in facility_ids else facility_ids[0]
        )
        if st.session_state.get("facility_thread_id") != selected_thread:
            st.session_state["facility_selection"] = default_facility_id
            st.session_state["facility_thread_id"] = selected_thread
        elif st.session_state.get("facility_selection") not in facility_ids:
            st.session_state["facility_selection"] = default_facility_id

        facility_id = st.selectbox("Facility", facility_ids, key="facility_selection")
        facility_name = next((row["facility_name"] for row in facility_rows if row["facility_id"] == facility_id), facility_id)
        st.subheader(f"Dock board: {facility_name}")
        render_dock_board(conn, facility_id)

        st.subheader("Escalations")
        escalations = list_open_escalations(conn)
        if not escalations:
            st.success("No open escalations.")
        else:
            for record in escalations[:5]:
                with st.expander(f"{record['exception_id']} | {record['shipment_id']} | {record['driver_id']}"):
                    st.write(record)

        st.subheader("Audit log")
        audit_rows = list_audit_log(conn, limit=10)
        if audit_rows:
            st.caption(f"Latest {len(audit_rows)} audit events, newest first.")
            st.table(pd.DataFrame(audit_rows))
        else:
            st.caption("No audit events yet.")

        st.subheader("Integrity badge")
        st.markdown(f"<div style='padding:12px 16px; border-radius:10px; background:#111827; color:#F9FAFB; font-weight:700; width:fit-content'> {render_integrity_badge(conn)} </div>", unsafe_allow_html=True)

        if st.button("Simulate race"):
            try:
                from tests.test_concurrency import run_race

                run_race(3)
                st.success("Race simulation completed. Check terminal output for result.")
            except Exception as exc:  # pragma: no cover - UI safety path
                st.error(f"Race simulation failed: {exc}")


if __name__ == "__main__":
    main()
