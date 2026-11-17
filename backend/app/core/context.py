"""Per-request actor/trace context used by the audit mechanism and logs."""
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class Actor:
    actor_type: str = "system"
    actor_id: str | None = None
    ip: str | None = None


current_actor: ContextVar[Actor] = ContextVar("current_actor", default=Actor())
current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
