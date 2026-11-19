from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import periods
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.guards import facility_staff
from app.modules.analytics import scope as scopes
from app.modules.analytics import views
from app.modules.auth.deps import Principal, require
from app.modules.booking import service as booking_service
from app.modules.insights import optimiser, service

router = APIRouter(prefix="/insights", tags=["insights"])
read = require("ai_insights", "R")
plan_read = facility_staff("day_schedule", "R")


@router.get("/narrative")
async def get_narrative(view: str, range: str = "7d", date_from: datetime | None = None, date_to: datetime | None = None,
                        facility_id: UUID | None = None, carrier_id: UUID | None = None, lang: str = "en",
                        p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    """The same figures as /analytics/views/{view} (same scope rules), explained in words when AI is available."""
    if view not in views.VIEWS:
        raise NotFoundError("Unknown analytics view")
    sc = scopes.build(p, facility_id=facility_id, carrier_id=carrier_id, view=view)
    result = await views.compute(db, view, sc, periods.resolve(range, date_from, date_to))
    key = f"{sc.label}:{sorted(map(str, sc.facility_ids or []))}:{sc.carrier_id}"
    return await service.narrative(view, result, scope_key=key, language=lang)


@router.get("/optimiser/proposal")
async def proposal(facility_id: UUID, day: date | None = None, p: Principal = Depends(plan_read), db: AsyncSession = Depends(get_db)):
    """Read-only proposal for a facility day. It never changes a booking; the planner applies any move explicitly."""
    fac = await booking_service.resolve_facility(db, p, facility_id)
    d = day or booking_service.local_today(fac.timezone)
    start, end = booking_service.day_bounds(d, fac.timezone)
    out = await optimiser.propose(db, fac.id, start, end, booking_service.now())
    return {"facility_id": fac.id, "facility": fac.facility_name, "date": d.isoformat(), **out}
