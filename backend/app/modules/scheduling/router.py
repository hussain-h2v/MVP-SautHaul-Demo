from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.guards import facility_staff
from app.modules.auth.deps import Principal
from app.modules.scheduling import service
from app.modules.scheduling.schemas import EtaOut, OptionOut, OptionsIn, OptionsOut
from app.modules.shipments import service as shipments_service

router = APIRouter(prefix="/scheduling", tags=["scheduling"])
read = facility_staff("booking_decisions", "R")


def to_out(shipment_id, res: service.OptionsResult, escalation_id=None, note=None) -> OptionsOut:
    opts = []
    for o in res.options:
        opts.append(OptionOut(
            rank=o.rank, slot_ids=list(o.slot_ids), slot_codes=[res.slots[i].code for i in o.slot_ids],
            dock_code=o.dock_code, dock_type=res.docks[o.dock_id].dock_type, start=o.start, end=o.end,
            needs_planner_approval=o.needs_planner_approval, reasons=o.reasons, explanation=o.explanation))
    e = res.eta
    return OptionsOut(
        shipment_id=shipment_id, total_feasible=res.total_feasible, options=opts, rejections=res.rejections,
        eta=EtaOut(ts=e.ts, source=e.source, confidence=e.confidence, upper_ts=e.upper_ts,
                   requires_human_review=e.requires_human_review) if e else None,
        escalation_id=escalation_id, note=note)


@router.post("/options", response_model=OptionsOut)
async def options(body: OptionsIn, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    """Read-only. Never creates a hold: showing an option is not reserving it."""
    await shipments_service.get_scoped(db, p, body.shipment_id)
    res = await service.find_options(db, body.shipment_id, effective_eta=body.effective_eta,
                                     latest_finish=body.latest_finish, limit=body.limit)
    return to_out(body.shipment_id, res)
