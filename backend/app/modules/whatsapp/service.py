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
