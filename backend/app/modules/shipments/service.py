from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.shipments import repository
from app.modules.shipments.schemas import ShipmentPage


async def list_shipments(db: AsyncSession, p: Principal, limit: int, offset: int) -> ShipmentPage:
    total, rows = await repository.list_page(db, p, limit, offset)
    return ShipmentPage(total=total, items=rows)  # type: ignore[arg-type]
