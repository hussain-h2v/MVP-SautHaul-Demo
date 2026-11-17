from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_activity_service as service
from app.modules.coordinator.desk_activity_service import ActivityRow
from app.modules.coordinator.desk_common import desk_reader

router = APIRouter(prefix="/coordinator/activity", tags=["coordinator-desk"])


@router.get("", response_model=list[ActivityRow])
async def my_activity(limit: int = Query(50, ge=1, le=200), p: Principal = Depends(desk_reader),
                      db: AsyncSession = Depends(get_db)):
    """Only the caller's own actions: a coordinator can review their decisions, never someone else's."""
    return await service.activity(db, p, limit)
