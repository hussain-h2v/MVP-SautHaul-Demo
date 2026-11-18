"""Single shared audit mechanism: a SQLAlchemy session hook writes an audit_log row for
every insert/update/delete of any mapped entity (except AuditLog itself), in the same
transaction, tagged with the current actor (user/driver/bot/system/ai)."""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.context import current_actor, current_trace_id

SENSITIVE = {"password_hash", "totp_secret", "refresh_hash", "token_hash", "encrypted_key"}
# High-volume projection tables: their origin (outbox_events, state changes) is already audited.
IGNORED_TABLES = {"notifications", "notification_reads", "ai_usage_logs", "whatsapp_messages", "whatsapp_webhook_events"}  # high-volume append-only logs have their own record
_installed = False


def _jsonable(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, (UUID, Decimal)):
        return str(v)
    return v


def _cols(obj) -> list[str]:
    return [a.key for a in inspect(obj).mapper.column_attrs]


def _snapshot(obj) -> dict:
    return {c: ("***" if c in SENSITIVE else _jsonable(getattr(obj, c, None))) for c in _cols(obj)}


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    from app.modules.audit.models import AuditLog

    @event.listens_for(Session, "before_flush")
    def before_flush(session, ctx, instances):
        pending = session.info.setdefault("audit_pending", [])
        for obj in list(session.dirty):
            if isinstance(obj, AuditLog) or obj.__tablename__ in IGNORED_TABLES or not session.is_modified(obj):
                continue
            st = inspect(obj)
            before, after = {}, {}
            for a in st.mapper.column_attrs:
                h = st.attrs[a.key].history
                if h.has_changes() and a.key not in ("updated_at", "version"):
                    hide = a.key in SENSITIVE
                    before[a.key] = "***" if hide else _jsonable(h.deleted[0] if h.deleted else None)
                    after[a.key] = "***" if hide else _jsonable(h.added[0] if h.added else None)
            if after:
                pending.append(("update", obj, before, after))
        for obj in list(session.deleted):
            if not isinstance(obj, AuditLog) and obj.__tablename__ not in IGNORED_TABLES:
                pending.append(("delete", obj, _snapshot(obj), None))
        for obj in list(session.new):
            if not isinstance(obj, AuditLog) and obj.__tablename__ not in IGNORED_TABLES:
                pending.append(("insert", obj, None, None))

    @event.listens_for(Session, "after_flush_postexec")
    def after_flush_postexec(session, ctx):
        pending = session.info.pop("audit_pending", [])
        if not pending:
            return
        actor, trace = current_actor.get(), current_trace_id.get()
        for action, obj, before, after in pending:
            if action == "insert":
                after = _snapshot(obj)
            ident = getattr(obj, "id", None)
            session.add(
                AuditLog(
                    actor_type=actor.actor_type, actor_id=actor.actor_id, action=action,
                    entity=obj.__tablename__, entity_id=str(ident) if ident is not None else None,
                    before=before, after=after, ip=actor.ip, trace_id=trace,
                )
            )
