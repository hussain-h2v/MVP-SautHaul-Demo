from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.facilities import repository
from app.modules.facilities.schemas import FacilityPage


async def list_facilities(db: AsyncSession, p: Principal, limit: int, offset: int) -> FacilityPage:
    total, rows = await repository.list_page(db, p, limit, offset)
    return FacilityPage(total=total, items=rows)  # type: ignore[arg-type]
