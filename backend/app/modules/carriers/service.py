from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.carriers import repository
from app.modules.carriers.schemas import CarrierPage


async def list_carriers(db: AsyncSession, p: Principal, limit: int, offset: int) -> CarrierPage:
    total, rows = await repository.list_page(db, p, limit, offset)
    return CarrierPage(total=total, items=rows)  # type: ignore[arg-type]
