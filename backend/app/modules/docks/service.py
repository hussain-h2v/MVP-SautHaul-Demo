from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.docks.models import Dock


async def count_for_facility(db: AsyncSession, facility_id: UUID) -> int:
    return (await db.execute(select(func.count()).select_from(Dock).where(Dock.facility_id == facility_id))).scalar_one()
