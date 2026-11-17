from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.modules.auth.deps import Principal, require
from app.modules.settings.models import SystemSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingOut(BaseModel):
    key: str
    value: Any
    description: str | None


class SettingIn(BaseModel):
    value: Any


@router.get("", response_model=list[SettingOut])
async def list_settings(_: Principal = Depends(require("system_settings", "R")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SystemSetting).order_by(SystemSetting.key))).scalars().all()
    return [SettingOut(key=r.key, value=r.value, description=r.description) for r in rows]


@router.put("/{key}", response_model=SettingOut)
async def put_setting(key: str, body: SettingIn, p: Principal = Depends(require("system_settings", "W")),
                      db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Unknown setting")
    row.value = body.value
    row.updated_by = p.user_id
    await db.commit()
    return SettingOut(key=row.key, value=row.value, description=row.description)
