from __future__ import annotations

import os
import sqlite3
from typing import Any

from setuhaul.clock import SimClock
from setuhaul.conversation import Conversation
from setuhaul.llm_fallback import try_llm_fallback


class LLMAgent:
    """LLM-capable wrapper around the same deterministic tool flow.

    In production this would use a tool-calling model; in this project the
    offline fallback path remains the same as the scripted mode, so tests and
    replays stay deterministic without forcing a network dependency.
    """

    SYSTEM_PROMPT = (
        "You are the SetuHaul dispatch assistant. Only parse messy driver text, "
        "collect missing facts, suggest feasible options, and call the tools for "
        "holds or escalations. Never make capacity decisions yourself or invent "
        "availability; the database engine is the source of truth. Keep all "
        "driver-facing messages in clear English."
    )

    def __init__(self, conn: sqlite3.Connection, clock: SimClock, *, use_llm: bool = False, system_prompt: str | None = None):
        self.conn = conn
        self.clock = clock
        self.use_llm = use_llm or bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
        self.system_prompt = system_prompt or self.SYSTEM_PROMPT
        self.conversation = Conversation(conn, clock)

    def run(self, thread_id: str, message: str) -> str:
        if self.use_llm:
            # The LLM path is intentionally shallow here: the fallback parser keeps
            # the same deterministic logic and tool contracts as the scripted agent.
            parsed = try_llm_fallback(message, self.clock.now().hour)
            if parsed and isinstance(parsed, dict) and not parsed.get("_error"):
                # We simply reuse the same conversation pipeline.
                return self.conversation.handle_driver_message(thread_id, message)
        return self.conversation.handle_driver_message(thread_id, message)

    def handle_message(self, thread_id: str, message: str) -> str:
        return self.run(thread_id, message)

    def safe_run(self, thread_id: str, message: str) -> dict[str, Any]:
        try:
            return {"ok": True, "response": self.run(thread_id, message)}
        except Exception as exc:  # pragma: no cover - defensive wrapper
            return {"ok": False, "error": str(exc)}
