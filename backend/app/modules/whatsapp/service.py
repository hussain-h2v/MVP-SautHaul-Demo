from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.whatsapp.models import ChatMessage, ChatThread


async def last_activity_by_driver(db: AsyncSession, driver_ids: list[UUID]) -> dict[UUID, datetime]:
    rows = await db.execute(
        select(ChatThread.driver_id, func.max(ChatMessage.message_ts))
        .join(ChatMessage, ChatMessage.thread_id == ChatThread.id)
        .where(ChatThread.driver_id.in_(driver_ids)).group_by(ChatThread.driver_id))
    return {d: ts for d, ts in rows.all()}


async def threads_for_shipment(db: AsyncSession, shipment_id: UUID) -> list[ChatThread]:
    return list((await db.execute(select(ChatThread).where(ChatThread.shipment_id == shipment_id)
                                  .order_by(ChatThread.opened_at))).scalars().all())


async def latest_driver_message(db, thread_id):
    from sqlalchemy import select

    from app.modules.whatsapp.models import ChatMessage

    return (await db.execute(select(ChatMessage).where(ChatMessage.thread_id == thread_id, ChatMessage.sender_type == "DRIVER",
                                                       ChatMessage.is_duplicate.is_(False))
                             .order_by(ChatMessage.message_ts.desc()).limit(1))).scalar_one_or_none()


async def driver_messages_for_thread_codes(db, codes: list[str]) -> dict[str, list[tuple[str, str]]]:
    """thread code -> [(text, thread_intent)] of non-duplicate DRIVER messages in time order (used to seed the AI golden set)."""
    from sqlalchemy import select

    from app.modules.whatsapp.models import ChatMessage, ChatThread

    rows = await db.execute(
        select(ChatThread.code, ChatMessage.message_text, ChatThread.thread_intent).join(ChatMessage, ChatMessage.thread_id == ChatThread.id)
        .where(ChatThread.code.in_(codes), ChatMessage.sender_type == "DRIVER", ChatMessage.is_duplicate.is_(False))
        .order_by(ChatThread.code, ChatMessage.message_ts, ChatMessage.code))
    out: dict[str, list[tuple[str, str]]] = {}
    for code, text, intent in rows.all():
        out.setdefault(code, []).append((text, intent))
    return out


OPEN_THREAD_STATUSES = ("OPEN", "WAITING_FOR_DRIVER", "WAITING_FOR_WAREHOUSE")


async def get_or_create_thread(db, driver_id, now):
    """The driver's latest open conversation, else a new one (code THR<seq>)."""
    import uuid as _uuid

    from sqlalchemy import Integer, cast, func, select
    from sqlalchemy.exc import IntegrityError

    t = (await db.execute(select(ChatThread).where(ChatThread.driver_id == driver_id, ChatThread.thread_status.in_(OPEN_THREAD_STATUSES))
                          .order_by(ChatThread.opened_at.desc()).limit(1))).scalar_one_or_none()
    if t is not None:
        return t
    for _ in range(5):
        n = (await db.execute(select(func.max(cast(func.substr(ChatThread.code, 4), Integer))).where(ChatThread.code.op("~")("^THR[0-9]+$")))).scalar()
        t = ChatThread(code=f"THR{(n or 0) + 1:03d}", driver_id=driver_id, opened_at=now, thread_status="OPEN", thread_intent="UNKNOWN")
        try:
            async with db.begin_nested():
                db.add(t)
                await db.flush()
            return t
        except IntegrityError:
            if t in db:
                db.expunge(t)
    raise RuntimeError("could not allocate a thread code")
