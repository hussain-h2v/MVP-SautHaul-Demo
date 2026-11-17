from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.shipments import service
from app.modules.shipments.schemas import ShipmentPage

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("", response_model=ShipmentPage)
async def list_shipments(
    limit: int = Query(50, le=200), offset: int = 0,
    p: Principal = Depends(require("shipment_details", "R")), db: AsyncSession = Depends(get_db),
):
    return await service.list_shipments(db, p, limit, offset)
