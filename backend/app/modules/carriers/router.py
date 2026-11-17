from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.carriers import service
from app.modules.carriers.schemas import CarrierPage

router = APIRouter(prefix="/carriers", tags=["carriers"])


@router.get("", response_model=CarrierPage)
async def list_carriers(
    limit: int = Query(50, le=200), offset: int = 0,
    p: Principal = Depends(require("drivers_vehicles", "R")), db: AsyncSession = Depends(get_db),
):
    return await service.list_carriers(db, p, limit, offset)
