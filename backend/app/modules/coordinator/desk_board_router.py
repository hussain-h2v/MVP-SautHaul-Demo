from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_board_service as service
from app.modules.coordinator.desk_board_schemas import BoardOut
from app.modules.coordinator.desk_common import desk_reader

router = APIRouter(prefix="/coordinator/board", tags=["coordinator-desk"])


@router.get("", response_model=BoardOut)
async def board(facility_id: UUID | None = None, date: date | None = None, _: Principal = Depends(desk_reader),
                db: AsyncSession = Depends(get_db)):
    """Today's trucks across all facilities by stage; the date is read in each facility's own time zone."""
    return await service.board(db, facility_id, date)
