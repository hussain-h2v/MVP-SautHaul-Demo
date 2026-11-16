"""The conversation layer: one multi-turn state machine per driver thread.

This is the orchestrator the brief calls the "AI agent": it reads free text
(via nlu.py), asks clarifying questions, calls the business tools in
tools.py, and keeps context across turns. It never invents availability,
never decides priority, and never writes a booking except by calling
tools.hold_slot, which is the only place that touches the database's
concurrency guarantee.

Per-thread "memory" here (which options were just offered, what we are
waiting to hear back about) is intentionally NOT stored in the SQLite
system of record -- it is operational, short-lived conversational state,
not a business fact. Business facts (ETA updates, holds, confirmations,
escalations) are written to the database as they happen, through tools.py.

Language: the parser accepts English, Hindi, and Hinglish driver messages,
while every driver-facing reply is written in English. Internal records,
escalation summaries, and audit-log entries are also kept in English.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import llm_fallback, tools
from .clock import SimClock
from .nlu import ParsedMessage, parse_driver_message


@dataclass
class ThreadState:
    thread_id: str
    driver_id: str
    shipment_id: Optional[str] = None
    awaiting: Optional[str] = None  # None | 'SHIPMENT_CHOICE' | 'DELAY_MEANING'
    offered_options: list = field(default_factory=list)  # list[tools.SlotOption]
    pending_delay_minutes: Optional[int] = None
    last_message_text: Optional[str] = None
    latest_acceptable_hhmm: Optional[str] = None


class Conversation:
    def __init__(self, conn: sqlite3.Connection, clock: SimClock):
        self.conn = conn
        self.clock = clock
        self.threads: dict[str, ThreadState] = {}

    # -- plumbing ----------------------------------------------------

    def _state(self, thread_id: str) -> ThreadState:
        row = self.conn.execute(
            "SELECT driver_id, shipment_id FROM chat_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if thread_id not in self.threads:
            self.threads[thread_id] = ThreadState(
                thread_id=thread_id, driver_id=row["driver_id"], shipment_id=row["shipment_id"],
            )
        return self.threads[thread_id]

    def _log_message(self, thread_id: str, sender_type: str, text: str, *,
                      is_duplicate: bool = False, requires_review: bool = False) -> None:
        self.conn.execute(
            """
            INSERT INTO chat_messages (chat_message_id, thread_id, sender_type, message_text,
                message_ts, is_duplicate, requires_human_review)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tools.new_id("MSG"), thread_id, sender_type, text, self.clock.now_ts(),
             int(is_duplicate), int(requires_review)),
        )

    def _is_duplicate(self, thread_id: str, text: str) -> bool:
        """A retry, not a stale coincidence: same text, same thread, within
        a few minutes of simulated time. A seeded message from hours earlier
        that happens to read the same must never trip this."""
        row = self.conn.execute(
            "SELECT message_text, message_ts FROM chat_messages "
            "WHERE thread_id = ? AND sender_type = 'DRIVER' ORDER BY message_ts DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None or row["message_text"].strip() != text.strip():
            return False
        gap = (self.clock.now() - SimClock.parse(row["message_ts"])).total_seconds()
        return 0 <= gap <= 5 * 60

    def _today(self) -> str:
        return self.clock.now_ts()[:10]

    def _hhmm_to_ts(self, hhmm: str) -> str:
        return f"{self._today()}T{hhmm}:00+05:30"

    # -- main entry point ---------------------------------------------

    def handle_driver_message(self, thread_id: str, text: str) -> str:
        state = self._state(thread_id)

        if self._is_duplicate(thread_id, text):
            self._log_message(thread_id, "DRIVER", text, is_duplicate=True)
            reply = "Received — this appears to be the same message you just sent. I’m already handling it."
            self._log_message(thread_id, "AGENT", reply)
            return reply

        self._log_message(thread_id, "DRIVER", text)
        state.last_message_text = text

        if state.awaiting == "SHIPMENT_CHOICE":
            match = re.search(r"\bSHP\d{3,}\b", text, re.IGNORECASE)
            if match:
                chosen_id = match.group(0).upper()
                active = tools.find_driver_active_shipments(self.conn, state.driver_id)
                if any(r["shipment_id"] == chosen_id for r in active):
                    state.shipment_id = chosen_id
                    state.awaiting = None
                    self.conn.execute(
                        "UPDATE chat_threads SET shipment_id = ? WHERE thread_id = ?",
                        (chosen_id, state.thread_id),
                    )
                    reply = f"Okay, {chosen_id}. When do you expect to arrive, or what would you like me to check?"
                    self._log_message(thread_id, "AGENT", reply)
                    return reply
            reply = "I couldn't identify the shipment. Please send its shipment ID, for example SHP1004."
            self._log_message(thread_id, "AGENT", reply)
            return reply

        parsed = parse_driver_message(text, current_hour=self.clock.now().hour)

        if state.shipment_id is None:
            reply = self._resolve_shipment(state, parsed)
            if reply:
                self._log_message(thread_id, "AGENT", reply)
                return reply

        if state.awaiting == "DELAY_MEANING":
            return self._handle_delay_meaning_answer(state, parsed, text)

        if parsed.wants_decline and state.offered_options:
            state.offered_options = []
            reply = "No problem. Tell me how late you are or what arrival time you need, and I'll check again."
            self._log_message(thread_id, "AGENT", reply)
            return reply

        if parsed.wants_confirmation and state.offered_options:
            return self._handle_selection(state, parsed)

        if parsed.is_status_check and not parsed.reports_delay:
            return self._handle_status_check(state)

        if parsed.reports_delay:
            return self._handle_delay_report(state, parsed, text)

        if parsed.wants_options_only or parsed.selection_time_hhmm:
            return self._offer_options(state, parsed)

        # The rule-based parser found no usable signal at all. Before asking
        # the driver to repeat themselves, try the one-call LLM fallback
        # (see llm_fallback.py) -- but only once; if it also comes back
        # empty, or fails, fall through to the same plain question as before.
        enriched = self._try_llm_fallback(parsed, text)
        if enriched is not None:
            if enriched.is_status_check and not enriched.reports_delay:
                return self._handle_status_check(state)
            if enriched.reports_delay:
                return self._handle_delay_report(state, enriched, text)
            if enriched.wants_options_only or enriched.selection_time_hhmm:
                return self._offer_options(state, enriched)

        reply = ("I couldn't tell whether you're reporting a delay, sharing an arrival time, "
                 "or asking about a dock slot. Please tell me when you expect to arrive or what you'd like to know.")
        self._log_message(thread_id, "AGENT", reply)
        return reply

    def _try_llm_fallback(self, parsed: ParsedMessage, text: str) -> Optional[ParsedMessage]:
        data = llm_fallback.try_llm_fallback(text, current_hour=self.clock.now().hour)
        if not data:
            return None
        merged = ParsedMessage(raw_text=parsed.raw_text)
        for field_name in merged.__dataclass_fields__:
            if field_name in data and data[field_name] is not None:
                setattr(merged, field_name, data[field_name])
        if not any([merged.reports_delay, merged.wants_options_only, merged.wants_confirmation,
                    merged.wants_decline, merged.is_status_check, merged.selection_time_hhmm]):
            return None  # the model also found nothing usable -- don't pretend otherwise
        return merged

    # -- sub-flows ------------------------------------------------------

    def _resolve_shipment(self, state: ThreadState, parsed: ParsedMessage) -> Optional[str]:
        active = tools.find_driver_active_shipments(self.conn, state.driver_id)
        if len(active) == 0:
            return ("I can't find an active shipment assigned to you. Please contact your dispatcher "
                    "so they can check your assignment.")
        if len(active) == 1:
            state.shipment_id = active[0]["shipment_id"]
            self.conn.execute(
                "UPDATE chat_threads SET shipment_id = ? WHERE thread_id = ?",
                (state.shipment_id, state.thread_id),
            )
            return None
        state.awaiting = "SHIPMENT_CHOICE"
        options = ", ".join(f"{r['shipment_id']} ({r['customer_name']})" for r in active)
        return f"You have more than one active shipment: {options}. Which shipment are you asking about?"

    def _handle_delay_meaning_answer(self, state: ThreadState, parsed: ParsedMessage, text: str) -> str:
        state.awaiting = None
        answer = parse_driver_message(text, current_hour=self.clock.now().hour)
        if answer.explicit_time_hhmm:
            declared_ts = self._hhmm_to_ts(answer.explicit_time_hhmm)
            reply = self._apply_eta(state, declared_ts, confidence="HIGH", reason_code=None)
        else:
            # Driver confirmed it's a repair/duration figure, not a new arrival time.
            # We still need *an* arrival estimate, so we use it as a delay from the
            # last known ETA, but at lower confidence -- this is a documented
            # limitation (decision register #3): we did not get a clean new ETA.
            minutes = state.pending_delay_minutes
            state.pending_delay_minutes = None
            reply = self._apply_delay(state, minutes, reason_code=None, confidence="LOW")
        return reply

    def _handle_delay_report(self, state: ThreadState, parsed: ParsedMessage, text: str) -> str:
        if parsed.latest_acceptable_hhmm:
            state.latest_acceptable_hhmm = parsed.latest_acceptable_hhmm

        if parsed.explicit_time_hhmm:
            declared_ts = self._hhmm_to_ts(parsed.explicit_time_hhmm)
            return self._apply_eta(state, declared_ts, confidence="HIGH", reason_code=parsed.reason_code)

        if parsed.ambiguous_duration:
            state.awaiting = "DELAY_MEANING"
            state.pending_delay_minutes = parsed.delay_minutes
            reply = (f"Does {parsed.delay_minutes} minutes mean you will arrive that much later, "
                     "or was that only the time needed for repairs? I need your estimated arrival time, "
                     "not the repair duration.")
            self._log_message(state.thread_id, "AGENT", reply, requires_review=True)
            return reply

        if parsed.delay_minutes is not None:
            return self._apply_delay(state, parsed.delay_minutes, reason_code=parsed.reason_code,
                                      confidence="MEDIUM")

        reply = "Thanks for the update. Please share your estimated arrival time or how many minutes late you are."
        self._log_message(state.thread_id, "AGENT", reply)
        return reply

    def _apply_delay(self, state: ThreadState, minutes: Optional[int], *,
                      reason_code: Optional[str], confidence: str) -> str:
        if minutes is None:
            return "I need either your estimated arrival time or the number of minutes you are delayed to check slots."
        snap = tools.get_shipment_snapshot(self.conn, state.shipment_id)
        baseline = SimClock.parse(snap["effective_eta_ts"])
        from datetime import timedelta
        new_eta = baseline + timedelta(minutes=minutes)
        declared_ts = SimClock.format(new_eta)
        return self._apply_eta(state, declared_ts, confidence=confidence, reason_code=reason_code)

    def _apply_eta(self, state: ThreadState, declared_ts: str, *, confidence: str,
                    reason_code: Optional[str]) -> str:
        tools.record_eta_update(
            self.conn, self.clock, shipment_id=state.shipment_id, declared_eta_ts=declared_ts,
            source_type="DRIVER_DECLARED", confidence_code=confidence, delay_reason_code=reason_code,
            reported_by_driver_id=state.driver_id, note=state.last_message_text or "",
        )
        return self._offer_options_for_eta(state, declared_ts)

    def _handle_status_check(self, state: ThreadState) -> str:
        snap = tools.get_shipment_snapshot(self.conn, state.shipment_id)
        if snap["shipment"]["current_status"] == "CANCELLED":
            reply = "This shipment and its appointment have been cancelled. Please contact your dispatcher to make a new plan."
        elif snap.get("slot_start_ts"):
            reply = (f"Your current booking is at dock {snap['planned_dock_code']} "
                     f"from {snap['slot_start_ts'][11:16]} to {snap['slot_end_ts'][11:16]}.")
        else:
            reply = "I can't find an active appointment for this shipment."
        self._log_message(state.thread_id, "AGENT", reply)
        return reply

    def _offer_options(self, state: ThreadState, parsed: ParsedMessage) -> str:
        snap = tools.get_shipment_snapshot(self.conn, state.shipment_id)
        after_ts = snap["effective_eta_ts"]
        if parsed.selection_time_hhmm:
            candidate = self._hhmm_to_ts(parsed.selection_time_hhmm)
            if candidate > after_ts:
                after_ts = candidate
        return self._offer_options_for_eta(state, after_ts)

    def _offer_options_for_eta(self, state: ThreadState, after_ts: str) -> str:
        latest = self._hhmm_to_ts(state.latest_acceptable_hhmm) if state.latest_acceptable_hhmm else None
        opts = tools.find_feasible_slots(
            self.conn, self.clock, shipment_id=state.shipment_id, after_ts=after_ts,
            latest_acceptable_ts=latest,
        )
        state.offered_options = opts
        if not opts:
            record = tools.escalate(
                self.conn, self.clock, thread_id=state.thread_id, driver_id=state.driver_id,
                shipment_id=state.shipment_id, trigger="NO_FEASIBLE_SLOT",
                summary=f"No compatible, open slot found at or after {after_ts}.",
                recommended_action="A coordinator must manually source capacity or renegotiate the window.",
            )
            reply = (f"I couldn't find a compatible slot after {after_ts[11:16]}. Docks may be booked, "
                     f"blocked, or outside operating hours. I've escalated this to Operations "
                     f"(case {record.exception_id}); they will contact you.")
            self._log_message(state.thread_id, "AGENT", reply)
            return reply

        lines = []
        for i, o in enumerate(opts, start=1):
            flag = " (manager approval required)" if o.requires_manual_approval else ""
            lines.append(f"{i}) Dock {o.dock_code} ({o.dock_type.title()}) -- "
                          f"{o.slot_start_ts[11:16]} to {o.slot_end_ts[11:16]}{flag}")
        reply = ("These slots are available (not booked yet — tell me which one you want me to hold):\n"
                 + "\n".join(lines))
        self._log_message(state.thread_id, "AGENT", reply)
        return reply

    def _handle_selection(self, state: ThreadState, parsed: ParsedMessage) -> str:
        chosen = None
        if parsed.selection_ordinal is not None:
            if 1 <= parsed.selection_ordinal <= len(state.offered_options):
                chosen = state.offered_options[parsed.selection_ordinal - 1]
            else:
                reply = (f"I offered {len(state.offered_options)} options. Please choose a number "
                         f"from 1 to {len(state.offered_options)} or name an offered dock.")
                self._log_message(state.thread_id, "AGENT", reply)
                return reply
        elif parsed.selection_dock_code:
            matches = [
                option for option in state.offered_options
                if option.dock_code.casefold() == parsed.selection_dock_code.casefold()
            ]
            if len(matches) == 1:
                chosen = matches[0]
            elif len(matches) > 1:
                times = ", ".join(option.slot_start_ts[11:16] for option in matches)
                reply = (f"Dock {parsed.selection_dock_code} has multiple offered times: {times}. "
                         "Please choose a time.")
                self._log_message(state.thread_id, "AGENT", reply)
                return reply
            else:
                offered_docks = ", ".join(
                    dict.fromkeys(option.dock_code for option in state.offered_options)
                )
                reply = (f"I didn't offer dock {parsed.selection_dock_code}. "
                         f"Please choose one of the offered docks: {offered_docks}.")
                self._log_message(state.thread_id, "AGENT", reply)
                return reply
        elif state.offered_options:
            # No option named: default to the earliest (first-listed, i.e. our
            # own top recommendation) rather than asking again for a generic
            # "take it" / "that works" confirmation.
            chosen = state.offered_options[0]
        if chosen is None:
            reply = "Which option would you like — the first or the second?"
            self._log_message(state.thread_id, "AGENT", reply)
            return reply

        if not tools.recheck_slot_available(self.conn, self.clock, chosen.slot_id):
            reply_prefix = "That slot has just been taken by another truck. "
            state.offered_options = []
            self._log_message(state.thread_id, "AGENT", reply_prefix, requires_review=False)
            follow_up = self._offer_options_for_eta(
                state, tools.get_shipment_snapshot(self.conn, state.shipment_id)["effective_eta_ts"]
            )
            return reply_prefix + follow_up

        result = tools.hold_slot(
            self.conn, self.clock, shipment_id=state.shipment_id, slot_id=chosen.slot_id,
            booking_source="DRIVER_CHAT", thread_id=state.thread_id,
        )
        if not result.ok:
            state.offered_options = []
            reply_prefix = "That slot was taken while we were talking. "
            self._log_message(state.thread_id, "AGENT", reply_prefix)
            follow_up = self._offer_options_for_eta(
                state, tools.get_shipment_snapshot(self.conn, state.shipment_id)["effective_eta_ts"]
            )
            return reply_prefix + follow_up

        if chosen.requires_manual_approval:
            reply = (f"I've placed a hold on dock {chosen.dock_code} at {chosen.slot_start_ts[11:16]}, "
                     f"but {chosen.reason_if_flagged} A coordinator must approve it before I can confirm. "
                     f"Appointment reference {result.appointment_id}.")
            tools.escalate(
                self.conn, self.clock, thread_id=state.thread_id, driver_id=state.driver_id,
                shipment_id=state.shipment_id, trigger="MANUAL_APPROVAL_REQUIRED",
                summary=f"Driver-requested slot {chosen.slot_id} starts after the facility's last-new-start rule.",
                recommended_action="Approve or reject the held appointment before its hold expires.",
            )
        else:
            tools.confirm_appointment(self.conn, self.clock, appointment_id=result.appointment_id,
                                       thread_id=state.thread_id)
            reply = (f"Booked. Dock {chosen.dock_code}, {chosen.slot_start_ts[11:16]} to "
                     f"{chosen.slot_end_ts[11:16]}. Appointment reference {result.appointment_id}.")
        state.offered_options = []
        self._log_message(state.thread_id, "AGENT", reply)
        return reply
