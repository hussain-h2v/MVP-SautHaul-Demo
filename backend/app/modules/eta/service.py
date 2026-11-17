from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class EffectiveEta:
    ts: datetime
    source: str
    confidence: str
    upper_ts: datetime | None
    requires_human_review: bool
    updated_at: datetime | None


async def effective_eta(db: AsyncSession, shipment_id: UUID) -> EffectiveEta | None:
    """Latest ETA update (history is never overwritten); for a range the upper bound is used. A range or a
    LOW-confidence (vague) ETA sets requires_human_review. Falls back to the shipment's plan."""
    from app.modules.shipments import service as shipments_service

    latest = (await db.execute(select(EtaUpdate).where(EtaUpdate.shipment_id == shipment_id)
                               .order_by(EtaUpdate.created_at.desc(), EtaUpdate.id.desc()).limit(1))).scalar_one_or_none()
    if latest is not None:
        ts = latest.declared_eta_upper_ts or latest.declared_eta_ts
        return EffectiveEta(ts, latest.source_type, latest.confidence_code, latest.declared_eta_upper_ts,
                            latest.confidence_code == "LOW" or latest.declared_eta_upper_ts is not None, latest.created_at)
    s = (await shipments_service.get_many(db, [shipment_id])).get(shipment_id)
    if s is None:
        return None
    return EffectiveEta(s.latest_eta_ts or s.original_eta_ts, "ORIGINAL_PLAN", "HIGH", None, False, None)


async def record_update(db: AsyncSession, shipment_id: UUID, *, source_type: str, declared_eta_ts: datetime,
                        upper_ts: datetime | None = None, confidence: str = "MEDIUM", reason: str | None = None,
                        note: str | None = None, driver_id: UUID | None = None) -> EtaUpdate:
    from app.modules.shipments import service as shipments_service

    if upper_ts is not None and upper_ts < declared_eta_ts:
        raise ValueError("upper bound must not be before the declared ETA")
    u = EtaUpdate(shipment_id=shipment_id, source_type=source_type, reported_by_driver_id=driver_id,
                  declared_eta_ts=declared_eta_ts, declared_eta_upper_ts=upper_ts, confidence_code=confidence,
                  delay_reason_code=reason, note=note)
    db.add(u)
    await db.flush()
    await shipments_service.set_latest_eta(db, shipment_id, upper_ts or declared_eta_ts)
    return u
