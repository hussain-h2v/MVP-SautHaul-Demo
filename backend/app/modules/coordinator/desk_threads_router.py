from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_threads_service as service
from app.modules.coordinator.desk_common import desk_reader, desk_writer, publish_inbox
from app.modules.coordinator.desk_threads_schemas import (
    DraftOut, ReplyIn, ReplyOut, ThreadItem, ThreadMessages, ThreadPage,
)

router = APIRouter(prefix="/coordinator/threads", tags=["coordinator-desk"])


@router.get("", response_model=ThreadPage)
async def list_threads(q: str | None = None, status: str | None = None, taken_over: bool | None = None,
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       _: Principal = Depends(desk_reader), db: AsyncSession = Depends(get_db)):
    return await service.list_threads(db, q, status, taken_over, limit, offset)


@router.get("/{thread_id}/messages", response_model=ThreadMessages)
async def messages(thread_id: UUID, _: Principal = Depends(desk_reader), db: AsyncSession = Depends(get_db)):
    return await service.thread_messages(db, thread_id)


@router.get("/{thread_id}/draft", response_model=DraftOut)
async def draft(thread_id: UUID, _: Principal = Depends(desk_reader), db: AsyncSession = Depends(get_db)):
    return await service.draft(db, thread_id)


@router.post("/{thread_id}/takeover", response_model=ThreadItem)
async def takeover(thread_id: UUID, p: Principal = Depends(desk_writer), db: AsyncSession = Depends(get_db)):
    item = await service.takeover(db, p, thread_id)
    await db.commit()
    await publish_inbox("thread.takeover", thread_id=str(thread_id))
    return item


@router.post("/{thread_id}/handback", response_model=ThreadItem)
async def handback(thread_id: UUID, p: Principal = Depends(desk_writer), db: AsyncSession = Depends(get_db)):
    item = await service.handback(db, p, thread_id)
    await db.commit()
    await publish_inbox("thread.handback", thread_id=str(thread_id))
    return item


@router.post("/{thread_id}/reply", response_model=ReplyOut, status_code=201)
async def reply(thread_id: UUID, body: ReplyIn, p: Principal = Depends(desk_writer), db: AsyncSession = Depends(get_db)):
    out = await service.reply(db, p, thread_id, body.text)
    await db.commit()
    await publish_inbox("thread.reply", thread_id=str(thread_id))
    return out
