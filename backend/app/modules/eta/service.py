from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eta.models import EtaUpdate


async def history(db: AsyncSession, shipment_id: UUID) -> list[EtaUpdate]:
    return list((await db.execute(
        select(EtaUpdate).where(EtaUpdate.shipment_id == shipment_id).order_by(EtaUpdate.created_at, EtaUpdate.id)
    )).scalars().all())
