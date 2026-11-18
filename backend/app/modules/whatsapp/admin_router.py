from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, require
from app.modules.whatsapp import admin_service as svc

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
read = require("system_settings", "R")
write = require("system_settings", "W")


class TemplateIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    language: str = Field(min_length=2, max_length=10)
    category: str | None = "UTILITY"
    body: str = Field(min_length=3, max_length=1024)
    variables: list[str] | None = None
    buttons: list[dict] | None = None


class TemplatePatch(BaseModel):
    body: str | None = Field(default=None, min_length=3, max_length=1024)
    approval_status: str | None = None
    needs_native_review: bool | None = None
    buttons: list[dict] | None = None


class OptIn(BaseModel):
    opted_in: bool


class SimulatorIn(BaseModel):
    driver_id: UUID | None = None
    number: str | None = Field(default=None, pattern=r"^\+?[0-9]{8,15}$")
    kind: str = "text"
    text: str | None = Field(default=None, max_length=1000)
    button_id: str | None = Field(default=None, max_length=256)
    list_id: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=256)


@router.get("/status")
async def status(_: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.status(db)


@router.get("/templates")
async def templates(language: str | None = None, name: str | None = None, _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.list_templates(db, language, name)


@router.post("/templates", status_code=201)
async def create_template(body: TemplateIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out = await svc.create_template(db, body.model_dump())
    await db.commit()
    return out


@router.patch("/templates/{template_id}")
async def update_template(template_id: UUID, body: TemplatePatch, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out = await svc.update_template(db, template_id, body.model_dump(exclude_unset=True))
    await db.commit()
    return out


@router.get("/failures")
async def failures(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), _: Principal = Depends(read),
                   db: AsyncSession = Depends(get_db)):
    return await svc.failures(db, limit, offset)


@router.get("/messages")
async def messages(driver_id: UUID | None = None, thread_id: UUID | None = None, direction: str | None = Query(None, pattern="^(in|out)$"),
                   status: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.messages(db, driver_id, thread_id, direction, status, q, limit, offset)


@router.get("/opt-ins")
async def opt_ins(state: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  _: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await svc.opt_ins(db, state, limit, offset)


@router.post("/opt-ins/{driver_id}")
async def set_opt_in(driver_id: UUID, body: OptIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    out = await svc.set_opt_in(db, driver_id, body.opted_in)
    await db.commit()
    return out


@router.post("/simulator/send")
async def simulator_send(body: SimulatorIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    return await svc.simulator_send(db, body.model_dump())


@router.get("/simulator/conversation")
async def simulator_conversation(driver_id: UUID, limit: int = Query(100, ge=1, le=500), _: Principal = Depends(read),
                                 db: AsyncSession = Depends(get_db)):
    return await svc.conversation(db, driver_id, limit)


@router.post("/simulator/reset")
async def simulator_reset(driver_id: UUID, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    n = await svc.reset(db, driver_id)
    await db.commit()
    return {"deleted": n}
