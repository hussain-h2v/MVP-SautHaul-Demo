"""Shared guards and helpers for the coordinator desk endpoints (conversations, board, handover, activity)."""
from fastapi import Depends

from app.core import events
from app.core.errors import ForbiddenError
from app.modules.auth.deps import Principal, get_principal, require

DESK_ROLES = ("admin", "coordinator")


async def desk_reader(p: Principal = Depends(get_principal)) -> Principal:
    """Coordinators and admin see everything; planners and carrier users are shut out."""
    if p.role not in DESK_ROLES:
        raise ForbiddenError("The coordinator desk is only available to coordinators and admins")
    return p


# Writes (takeover, hand-back, reply, handover save) are coordinator-only per the permission matrix.
desk_writer = require("escalations_takeover", "W")


async def publish_inbox(reason: str, **extra) -> None:
    try:
        await events.publish("inbox.changed", {"reason": reason, **extra})
    except Exception:  # live updates are best-effort; the write already committed
        pass
