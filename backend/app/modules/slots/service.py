from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.slots.models import AppointmentSlot


async def windows(db: AsyncSession, slot_ids: list[UUID]) -> dict[UUID, tuple[str, datetime, datetime]]:
    rows = await db.execute(select(AppointmentSlot.id, AppointmentSlot.code, AppointmentSlot.slot_start_ts,
                                   AppointmentSlot.slot_end_ts).where(AppointmentSlot.id.in_(slot_ids)))
    return {i: (c, s, e) for i, c, s, e in rows.all()}
