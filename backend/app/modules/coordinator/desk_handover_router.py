from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_handover_service as service
from app.modules.coordinator.desk_common import desk_reader, desk_writer, publish_inbox
from app.modules.coordinator.desk_handover_schemas import HandoverDraft, HandoverIn, HandoverOut

router = APIRouter(prefix="/coordinator/handover", tags=["coordinator-desk"])


@router.get("/draft", response_model=HandoverDraft)
async def draft(since: datetime | None = None, _: Principal = Depends(desk_reader), db: AsyncSession = Depends(get_db)):
    return await service.draft(db, since)


@router.get("", response_model=list[HandoverOut])
async def list_records(limit: int = Query(20, ge=1, le=100), _: Principal = Depends(desk_reader),
                       db: AsyncSession = Depends(get_db)):
    return await service.list_records(db, limit)


@router.post("", response_model=HandoverOut, status_code=201)
async def save(body: HandoverIn, p: Principal = Depends(desk_writer), db: AsyncSession = Depends(get_db)):
    out = await service.save(db, p, body)
    await db.commit()
    await publish_inbox("handover.saved")
    return out
