from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import periods
from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationAppError
from app.core.listing import csv_response
from app.modules.ai import monitoring as ai_monitoring
from app.modules.analytics import scope as scopes
from app.modules.analytics import views
from app.modules.auth.deps import Principal, require

router = APIRouter(prefix="/analytics/views", tags=["analytics"])
read = require("analytics", "R")


async def _compute(db: AsyncSession, p: Principal, view: str, range_: str, date_from: datetime | None, date_to: datetime | None,
                   facility_id: UUID | None, carrier_id: UUID | None):
    if view not in views.VIEWS:
        raise NotFoundError("Unknown analytics view")
    sc = scopes.build(p, facility_id=facility_id, carrier_id=carrier_id, view=view)
    period = periods.resolve(range_, date_from, date_to)
    return await views.compute(db, view, sc, period), sc


@router.get("/{view}")
async def get_view(view: str, range: str = "7d", date_from: datetime | None = None, date_to: datetime | None = None,
                   facility_id: UUID | None = None, carrier_id: UUID | None = None,
                   p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    result, _ = await _compute(db, p, view, range, date_from, date_to, facility_id, carrier_id)
    if view == "network":
        result["ai_spend"] = await ai_monitoring.spend_summary(db)
    return result


@router.get("/{view}/export.csv")
async def export_view(view: str, table: str = Query("series"), range: str = "7d", date_from: datetime | None = None,
                      date_to: datetime | None = None, facility_id: UUID | None = None, carrier_id: UUID | None = None,
                      p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    if view in views.VIEW_TABLES and table not in views.VIEW_TABLES[view]:
        raise ValidationAppError("table must be one of " + ", ".join(views.VIEW_TABLES[view]))
    result, _ = await _compute(db, p, view, range, date_from, date_to, facility_id, carrier_id)
    cols, rows = views.table_rows(result, table)
    return csv_response(f"{view}-{table}-{range}.csv", cols, rows)
