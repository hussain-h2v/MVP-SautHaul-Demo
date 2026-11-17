from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, get_principal
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationPage

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(unread_only: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                             p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    return await service.list_for(db, p, unread_only, limit, offset)


@router.post("/read-all")
async def read_all(p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    n = await service.read_all(db, p)
    await db.commit()
    return {"marked": n}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(notification_id: UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> None:
    await service.mark_read(db, p, notification_id)
    await db.commit()
