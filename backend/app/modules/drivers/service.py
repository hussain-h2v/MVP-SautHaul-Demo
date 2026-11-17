from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.drivers import repository
from app.modules.drivers.models import Driver
from app.modules.drivers.schemas import DriverOut, DriverPage
from app.modules.shipments import service as shipments_service
from app.modules.whatsapp import service as whatsapp_service


async def counts_by_carrier(db: AsyncSession, carrier_ids: list[UUID]) -> dict[UUID, int]:
    return await repository.counts_by_carrier(db, carrier_ids)


async def enrich(db: AsyncSession, rows: list[Driver]) -> list[DriverOut]:
    from app.modules.carriers import repository as carriers_repo  # avoid import cycle with carriers.service

    ids = [r.id for r in rows]
    names = await carriers_repo.names(db, list({r.carrier_id for r in rows}))
    active = await shipments_service.active_counts_by_driver(db, ids)
    last = await whatsapp_service.last_activity_by_driver(db, ids)
    return [
        DriverOut(
            id=r.id, code=r.code, carrier_id=r.carrier_id, carrier_name=names.get(r.carrier_id, ""),
            driver_name=r.driver_name, phone=r.phone, whatsapp_number=r.whatsapp_number,
            preferred_language=r.preferred_language, whatsapp_opt_in=r.whatsapp_opt_in,
            verified=r.verified_at is not None, driver_status=r.driver_status, licence_number=r.licence_number,
            active_shipments=active.get(r.id, 0), last_activity=last.get(r.id),
        )
        for r in rows
    ]


async def page(db: AsyncSession, p: Principal, filters: tuple, sort, limit: int, offset: int) -> DriverPage:
    total, rows = await repository.list_page(db, p, filters, sort, limit, offset)
    return DriverPage(total=total, items=await enrich(db, list(rows)))


async def names(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    return await repository.names(db, ids)
