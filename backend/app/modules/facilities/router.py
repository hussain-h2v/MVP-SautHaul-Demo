from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.facilities import service
from app.modules.facilities.schemas import FacilityPage

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get("", response_model=FacilityPage)
async def list_facilities(
    limit: int = Query(50, le=200), offset: int = 0,
    p: Principal = Depends(require("docks_slots_rules", "R")), db: AsyncSession = Depends(get_db),
):
    return await service.list_facilities(db, p, limit, offset)
