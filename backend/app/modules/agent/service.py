"""Driver agent entry point: one inbound WhatsApp message in, reviewed replies out. State per conversation thread is kept
by a PostgreSQL LangGraph checkpointer, so the dialogue resumes across messages, workers and restarts."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.agent.graph import build
from app.modules.agent.tools import AgentTools, Session
from app.modules.whatsapp.outbound import AgentReply, Button, OutboundMessage, Row

_setup_done = False


def _conn_string() -> str:
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres+asyncpg://", "postgresql://")


async def _saver_ctx():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    return AsyncPostgresSaver.from_conn_string(_conn_string())


def _to_message(m: dict, language: str) -> OutboundMessage:
    return OutboundMessage(
        kind=m["kind"], text=m["text"], language=language, purpose=m.get("purpose", ""), list_button=m.get("list_button"),
        buttons=[Button(b["id"], b["title"]) for b in m.get("buttons", [])], rows=[Row(r["id"], r["title"], r.get("description", "")) for r in m.get("rows", [])],
    ).validate()


async def handle_message(db: AsyncSession, *, driver_id: UUID, thread_id: UUID, text: str | None, button_id: str | None,
                         wa_message_id: str, now: datetime | None = None) -> AgentReply:
    global _setup_done
    now = now or datetime.now(UTC)
    tools = AgentTools(Session(db=db, driver_id=driver_id, thread_id=thread_id, now=now))
    graph = build(tools)
    async with (await _saver_ctx()) as saver:
        if not _setup_done:
            await saver.setup()
            _setup_done = True
        app = graph.compile(checkpointer=saver)
        out = await app.ainvoke({"inbound": {"text": text, "button_id": button_id, "wa_message_id": wa_message_id, "now": now.isoformat()}},
                                config={"configurable": {"thread_id": str(thread_id)}})
    lang = out.get("language", "en")
    return AgentReply(
        messages=[_to_message(m, lang) for m in out.get("outbound", [])], escalated=bool(out.get("escalated_now")), language=lang,
        intent=out.get("intent"), requires_human_review=bool(out.get("review")), stage=out.get("stage"),
        escalation_id=UUID(out["escalation_id"]) if out.get("escalation_id") else None)
