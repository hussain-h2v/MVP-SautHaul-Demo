from __future__ import annotations

import sqlite3
from typing import Any

from setuhaul.clock import SimClock
from setuhaul.conversation import Conversation, ThreadState


class ScriptedAgent:
    """Deterministic agent for tests and replayable scenario runs.

    This is the offline mode the brief asks for: same tools, same parsing,
    but no external API dependency. It simply delegates to the conversation
    layer which itself calls the deterministic tools in tools.py.
    """

    SYSTEM_PROMPT = (
        "You are the SetuHaul driver chat agent. Collect only missing facts "
        "(delay vs repair time, latest finish, which shipment), never promise a "
        "slot before a hold is created, explain refusals plainly, and escalate "
        "when no safe automatic decision is possible. Keep all driver-facing "
        "messages in clear English."
    )

    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: SimClock,
        *,
        system_prompt: str | None = None,
        conversation_states: dict[str, ThreadState] | None = None,
    ):
        self.conn = conn
        self.clock = clock
        self.system_prompt = system_prompt or self.SYSTEM_PROMPT
        self.conversation = Conversation(conn, clock)
        if conversation_states is not None:
            self.conversation.threads = conversation_states

    def run(self, thread_id: str, message: str) -> str:
        return self.conversation.handle_driver_message(thread_id, message)

    def handle_message(self, thread_id: str, message: str) -> str:
        return self.run(thread_id, message)

    def respond(self, thread_id: str, message: str) -> str:
        return self.run(thread_id, message)

    def safe_run(self, thread_id: str, message: str) -> dict[str, Any]:
        try:
            return {"ok": True, "response": self.run(thread_id, message)}
        except Exception as exc:  # pragma: no cover - defensive wrapper
            return {"ok": False, "error": str(exc)}
