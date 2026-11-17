"""Read queries for the conversation viewer. These read chat, driver, shipment and user tables directly (read-only):
no service functions exist for these joins yet (see docs/DECISIONS.md)."""
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.listing import search
from app.modules.drivers.models import Driver
from app.modules.shipments.models import Shipment
from app.modules.users.models import User
from app.modules.whatsapp.models import ChatMessage, ChatThread


def _base() -> Select:
    last = (select(ChatMessage.thread_id.label("tid"), func.max(ChatMessage.message_ts).label("last_ts"),
                   func.bool_or(ChatMessage.requires_human_review).label("review"))
            .group_by(ChatMessage.thread_id).subquery())
    stmt = (select(ChatThread, Driver, Shipment.code.label("shipment_code"), User.id.label("owner_id"),
                   User.full_name.label("owner_name"), last.c.last_ts, last.c.review)
            .join(Driver, Driver.id == ChatThread.driver_id)
            .outerjoin(Shipment, Shipment.id == ChatThread.shipment_id)
            .outerjoin(User, User.id == ChatThread.taken_over_by_user_id)
            .outerjoin(last, last.c.tid == ChatThread.id))
    return stmt, last


async def list_threads(db: AsyncSession, q: str | None, status: str | None, taken_over: bool | None,
                       limit: int, offset: int):
    stmt, last = _base()
    if (cond := search(q, Driver.driver_name, Driver.code, ChatThread.code, Shipment.code)) is not None:
        stmt = stmt.where(cond)
    if status:
        stmt = stmt.where(ChatThread.thread_status == status)
    if taken_over is not None:
        stmt = stmt.where(ChatThread.taken_over_by_user_id.is_not(None) if taken_over
                          else ChatThread.taken_over_by_user_id.is_(None))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = func.coalesce(last.c.last_ts, ChatThread.opened_at).desc()
    rows = (await db.execute(stmt.order_by(order, ChatThread.id).limit(limit).offset(offset))).all()
    return total, rows


async def get_thread_row(db: AsyncSession, thread_id: UUID):
    stmt, _ = _base()
    return (await db.execute(stmt.where(ChatThread.id == thread_id))).first()


async def last_message_texts(db: AsyncSession, thread_ids: list[UUID]) -> dict[UUID, str]:
    if not thread_ids:
        return {}
    rn = func.row_number().over(partition_by=ChatMessage.thread_id,
                                order_by=(ChatMessage.message_ts.desc(), ChatMessage.id.desc()))
    sub = select(ChatMessage.thread_id.label("tid"), ChatMessage.message_text.label("txt"), rn.label("rn")) \
        .where(ChatMessage.thread_id.in_(thread_ids)).subquery()
    rows = await db.execute(select(sub.c.tid, sub.c.txt).where(sub.c.rn == 1))
    return {tid: txt for tid, txt in rows.all()}


async def messages(db: AsyncSession, thread_id: UUID) -> list[ChatMessage]:
    return list((await db.execute(select(ChatMessage).where(ChatMessage.thread_id == thread_id)
                                  .order_by(ChatMessage.message_ts, ChatMessage.id))).scalars().all())


async def last_driver_intent(db: AsyncSession, thread_id: UUID) -> str | None:
    row = (await db.execute(
        select(ChatMessage.parsed_intent).where(ChatMessage.thread_id == thread_id, ChatMessage.sender_type == "DRIVER",
                                                ChatMessage.parsed_intent.is_not(None))
        .order_by(ChatMessage.message_ts.desc(), ChatMessage.id.desc()).limit(1))).first()
    return row[0] if row else None


async def lock_thread(db: AsyncSession, thread_id: UUID) -> ChatThread | None:
    return (await db.execute(select(ChatThread).where(ChatThread.id == thread_id).with_for_update()
                             .execution_options(populate_existing=True))).scalar_one_or_none()


async def get_driver(db: AsyncSession, driver_id: UUID) -> Driver | None:
    return await db.get(Driver, driver_id)


async def get_user(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)
