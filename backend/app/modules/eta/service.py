from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eta.models import EtaUpdate


async def history(db: AsyncSession, shipment_id: UUID) -> list[EtaUpdate]:
    return list((await db.execute(
        select(EtaUpdate).where(EtaUpdate.shipment_id == shipment_id).order_by(EtaUpdate.created_at, EtaUpdate.id)
    )).scalars().all())


async def latest_eta_for(db: AsyncSession, shipment_ids: list[UUID]) -> dict[UUID, dict]:
    """Effective ETA per shipment from the v_latest_eta view (latest ETA update, else shipment plan)."""
    if not shipment_ids:
        return {}
    from sqlalchemy import text

    rows = await db.execute(
        text("SELECT shipment_id, effective_eta_ts, eta_source, eta_confidence FROM v_latest_eta "
             "WHERE shipment_id = ANY(:ids)"), {"ids": list(shipment_ids)})
    return {r.shipment_id: {"eta_ts": r.effective_eta_ts, "eta_source": r.eta_source,
                            "eta_confidence": r.eta_confidence} for r in rows}
