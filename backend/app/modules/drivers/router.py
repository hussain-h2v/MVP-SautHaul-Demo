from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.drivers import service
from app.modules.drivers.schemas import DriverPage

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("", response_model=DriverPage)
async def list_drivers(
    limit: int = Query(50, le=200), offset: int = 0,
    p: Principal = Depends(require("drivers_vehicles", "R")), db: AsyncSession = Depends(get_db),
):
    return await service.list_drivers(db, p, limit, offset)
