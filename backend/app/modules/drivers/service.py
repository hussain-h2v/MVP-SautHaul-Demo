from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.drivers import repository
from app.modules.drivers.schemas import DriverPage


async def list_drivers(db: AsyncSession, p: Principal, limit: int, offset: int) -> DriverPage:
    total, rows = await repository.list_page(db, p, limit, offset)
    return DriverPage(total=total, items=rows)  # type: ignore[arg-type]
