from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.listing import ImportResult, csv_response
from app.modules.auth.deps import Principal, require
from app.modules.shipments import repository, service
from app.modules.shipments.schemas import (
    AssignIn, AssignmentCheck, AssignOut, CancelIn, OfferIn, ReassignIn, RespondIn, ShipmentIn, ShipmentOut,
    ShipmentPage, ShipmentPatch, Timeline,
)

router = APIRouter(prefix="/shipments", tags=["shipments"])
read = require("shipment_details", "R")
write = require("shipments_write", "W")
carrier_write = require("assign_driver_vehicle", "W")
CSV_FIELDS = ["code", "order_reference", "facility_code", "carrier_name", "driver_name", "customer_name", "origin_city",
              "product_category", "load_weight_kg", "required_dock_type", "priority_code", "requested_date",
              "expected_unload_min", "current_status", "offer_status"]


def _filters(q, status, priority, facility_id, carrier_id, offer_status) -> dict:
    return {"q": q, "status": status, "priority": priority, "facility_id": facility_id,
            "carrier_id": carrier_id, "offer_status": offer_status}


@router.get("", response_model=ShipmentPage)
async def list_shipments(
    q: str | None = None, status: str | None = None, priority: str | None = None, facility_id: UUID | None = None,
    carrier_id: UUID | None = None, offer_status: str | None = None, sort: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    total, rows = await repository.list_page(
        db, p, _filters(q, status, priority, facility_id, carrier_id, offer_status), sort, limit, offset)
    return ShipmentPage(total=total, items=await service.enrich(db, list(rows)))


@router.get("/export.csv")
async def export_shipments(
    q: str | None = None, status: str | None = None, priority: str | None = None, facility_id: UUID | None = None,
    carrier_id: UUID | None = None, offer_status: str | None = None, sort: str | None = None,
    p: Principal = Depends(read), db: AsyncSession = Depends(get_db),
):
    rows = await service.enrich(db, list(await repository.list_all(
        db, p, _filters(q, status, priority, facility_id, carrier_id, offer_status), sort)))
    return csv_response("shipments.csv", CSV_FIELDS, [r.model_dump() for r in rows])


@router.post("/import", response_model=ImportResult)
async def import_shipments(dry_run: bool = True, file: UploadFile = File(...),
                           _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    result = await service.import_csv(db, file, dry_run)
    if not dry_run and not result.errors:
        await db.commit()
    return result


@router.get("/{shipment_id}", response_model=ShipmentOut)
async def get_shipment(shipment_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    s = await service._get(db, p, shipment_id)
    return (await service.enrich(db, [s]))[0]


@router.get("/{shipment_id}/timeline", response_model=Timeline)
async def shipment_timeline(shipment_id: UUID, p: Principal = Depends(read), db: AsyncSession = Depends(get_db)):
    return await service.timeline(db, p, shipment_id)


@router.post("", response_model=ShipmentOut, status_code=201)
async def create_shipment(body: ShipmentIn, _: Principal = Depends(write), db: AsyncSession = Depends(get_db)):
    s = await service.create(db, body)
    await db.commit()
    return (await service.enrich(db, [s]))[0]


@router.patch("/{shipment_id}", response_model=ShipmentOut)
async def update_shipment(shipment_id: UUID, body: ShipmentPatch, p: Principal = Depends(write),
                          db: AsyncSession = Depends(get_db)):
    s = await service.update(db, p, shipment_id, body)
    await db.commit()
    return (await service.enrich(db, [s]))[0]


@router.post("/{shipment_id}/cancel", response_model=ShipmentOut)
async def cancel_shipment(shipment_id: UUID, body: CancelIn, p: Principal = Depends(write),
                          db: AsyncSession = Depends(get_db)):
    s = await service.cancel(db, p, shipment_id, body)
    await db.commit()
    return (await service.enrich(db, [s]))[0]


@router.post("/{shipment_id}/offer", response_model=ShipmentOut)
async def offer_shipment(shipment_id: UUID, body: OfferIn, p: Principal = Depends(write),
                         db: AsyncSession = Depends(get_db)):
    s = await service.offer(db, p, shipment_id, body)
    await db.commit()
    await service.publish_offer(s)
    return (await service.enrich(db, [s]))[0]


async def _publish(s, kind: str) -> None:
    try:
        await service.events.publish(kind, {"shipment_id": str(s.id), "code": s.code},
                                     facility_id=s.destination_facility_id, carrier_id=s.carrier_id)
    except Exception:
        pass


@router.post("/{shipment_id}/respond", response_model=ShipmentOut)
async def respond(shipment_id: UUID, body: RespondIn, p: Principal = Depends(carrier_write), db: AsyncSession = Depends(get_db)):
    s = await service.respond(db, p, shipment_id, body)
    await db.commit()
    await _publish(s, "shipment.offer_responded")
    return (await service.enrich(db, [s]))[0]


@router.get("/{shipment_id}/assignment-check", response_model=AssignmentCheck)
async def assignment_check(shipment_id: UUID, driver_id: UUID, vehicle_id: UUID, p: Principal = Depends(carrier_write),
                           db: AsyncSession = Depends(get_db)):
    check, _ = await service.assignment_check(db, p, shipment_id, driver_id, vehicle_id)
    return check


@router.post("/{shipment_id}/assign", response_model=AssignOut)
async def assign(shipment_id: UUID, body: AssignIn, p: Principal = Depends(carrier_write), db: AsyncSession = Depends(get_db)):
    s, check = await service.assign(db, p, shipment_id, body.driver_id, body.vehicle_id)
    await db.commit()
    await _publish(s, "shipment.assigned")
    return AssignOut(shipment=(await service.enrich(db, [s]))[0], warnings=check.warnings, driver_language=check.driver_language)


@router.post("/{shipment_id}/reassign", response_model=AssignOut)
async def reassign(shipment_id: UUID, body: ReassignIn, p: Principal = Depends(carrier_write), db: AsyncSession = Depends(get_db)):
    s, check = await service.reassign(db, p, shipment_id, body.driver_id, body.vehicle_id, body.reason)
    await db.commit()
    await _publish(s, "shipment.reassigned")
    return AssignOut(shipment=(await service.enrich(db, [s]))[0], warnings=check.warnings, driver_language=check.driver_language)
