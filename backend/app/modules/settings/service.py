from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.settings.models import SystemSetting


async def get_value(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = (await db.execute(select(SystemSetting.value).where(SystemSetting.key == key))).first()
    return default if row is None or row[0] is None else row[0]
