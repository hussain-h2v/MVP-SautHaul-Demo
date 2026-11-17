import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError, ValidationAppError
from app.core.listing import ImportError_, ImportResult, read_csv
from app.core.outbox import emit
from app.core.security import encrypt_secret, sha256
from app.modules.auth.deps import Principal
from app.modules.drivers import repository
from app.modules.drivers.models import Driver
from app.modules.drivers.schemas import (
    DriverDetail, DriverIn, DriverOut, DriverPage, DriverPatch, HistoryRow, VerificationSent,
)
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


CSV_COLUMNS = ["driver_name", "phone", "whatsapp_number", "preferred_language", "licence_number", "home_base_city"]
VERIFY_TTL_MIN = 10
VERIFY_MAX_ATTEMPTS = 5


class TooManyAttempts(AppError):
    status_code = 429

    def __init__(self, message: str = "Too many attempts, try again later") -> None:
        super().__init__("RATE_LIMITED", message)


def _carrier(p: Principal) -> UUID:
    if p.carrier_id is None:
        raise ValidationAppError("Only carrier users can manage a carrier's drivers")
    return p.carrier_id


async def get_scoped(db: AsyncSession, p: Principal, driver_id: UUID) -> Driver:
    d = await repository.get(db, p, driver_id)
    if d is None:
        raise NotFoundError("Driver not found")
    return d


async def detail(db: AsyncSession, p: Principal, driver_id: UUID) -> DriverDetail:
    d = await get_scoped(db, p, driver_id)
    base = (await enrich(db, [d]))[0]
    rows = await shipments_service.history_for_driver(db, d.id)
    return DriverDetail(**base.model_dump(), home_base_city=d.home_base_city,
                        history=[HistoryRow(**r) for r in rows])


async def _unique(db: AsyncSession, phone: str | None, licence: str | None, whatsapp: str | None, me: UUID | None) -> None:
    for value, finder, label in ((phone, repository.by_phone, "phone number"), (licence, repository.by_licence, "licence number"),
                                 (whatsapp, repository.by_whatsapp, "WhatsApp number")):
        if value:
            other = await finder(db, value)
            if other is not None and other.id != me:
                raise ConflictError("DUPLICATE", f"A driver with this {label} already exists")


async def create(db: AsyncSession, p: Principal, body: DriverIn) -> Driver:
    carrier_id = _carrier(p)
    await _unique(db, body.phone, body.licence_number, body.whatsapp_number, None)
    d = Driver(code=await repository.next_code(db), carrier_id=carrier_id, driver_name=body.driver_name, phone=body.phone,
               licence_number=body.licence_number, home_base_city=body.home_base_city, driver_status="ACTIVE",
               whatsapp_number=body.whatsapp_number, preferred_language=body.preferred_language,
               whatsapp_opt_in=False, verified_at=None)
    db.add(d)
    await db.flush()
    return d


async def update(db: AsyncSession, p: Principal, driver_id: UUID, body: DriverPatch) -> Driver:
    d = await get_scoped(db, p, driver_id)
    data = body.model_dump(exclude_unset=True)
    await _unique(db, data.get("phone"), data.get("licence_number"), data.get("whatsapp_number"), d.id)
    if "whatsapp_number" in data and data["whatsapp_number"] != d.whatsapp_number:
        d.verified_at, d.whatsapp_opt_in = None, False  # a new number must be verified again
        d.verification_code_hash = d.verification_expires_at = None
        d.verification_attempts = 0
    if data.get("driver_status") in ("INACTIVE", "OFF_DUTY") and d.driver_status == "ACTIVE":
        if (await shipments_service.active_counts_by_driver(db, [d.id])).get(d.id) and data["driver_status"] == "INACTIVE":
            raise ConflictError("ACTIVE_SHIPMENTS", "This driver is on an active shipment; reassign it first")
    if d.driver_status == "SUSPENDED" and "driver_status" in data:
        raise ConflictError("SUSPENDED", "A suspended driver can only be reinstated by SetuHaul operations")
    for k, val in data.items():
        setattr(d, k, val)
    return d


async def deactivate(db: AsyncSession, p: Principal, driver_id: UUID) -> Driver:
    d = await get_scoped(db, p, driver_id)
    if (await shipments_service.active_counts_by_driver(db, [d.id])).get(d.id):
        raise ConflictError("ACTIVE_SHIPMENTS", "This driver is on an active shipment; reassign it first")
    d.driver_status = "INACTIVE"
    return d


async def request_verification(db: AsyncSession, p: Principal, driver_id: UUID, redis=None) -> VerificationSent:
    """Sends a template message (outbox; delivered by the WhatsApp worker in M8) holding a one-time code. The driver
    replying with the code proves they control the number."""
    from app.core.config import get_settings
    from app.modules.auth.service import RateLimitedError, rate_limit

    d = await get_scoped(db, p, driver_id)
    if not d.whatsapp_number:
        raise ValidationAppError("Add a WhatsApp number first")
    try:
        await rate_limit(redis, f"wa-verify:{d.id}", 5, 3600)
    except RateLimitedError:
        raise TooManyAttempts("Verification can be requested 5 times per hour") from None
    code = f"{secrets.randbelow(1_000_000):06d}"
    d.verification_code_hash = sha256(f"{d.id}:{code}")
    d.verification_expires_at = datetime.now(UTC) + timedelta(minutes=VERIFY_TTL_MIN)
    d.verification_attempts = 0
    emit(db, "whatsapp.verification", {"driver_id": d.id, "to": d.whatsapp_number, "language": d.preferred_language,
                                       "template": "verification", "code_enc": encrypt_secret(code)})
    dev = code if get_settings().env != "production" else None
    return VerificationSent(sent=True, expires_at=d.verification_expires_at, dev_code=dev)


async def confirm_verification(db: AsyncSession, driver: Driver, code: str) -> None:
    """Checks the code. Used by the carrier portal now and by the WhatsApp reply handler in M8."""
    now = datetime.now(UTC)
    if not driver.verification_code_hash or not driver.verification_expires_at or driver.verification_expires_at < now:
        raise ValidationAppError("No active verification code; request a new one")
    if driver.verification_attempts >= VERIFY_MAX_ATTEMPTS:
        raise TooManyAttempts("Too many wrong codes; request a new one")
    driver.verification_attempts += 1
    if sha256(f"{driver.id}:{code}") != driver.verification_code_hash:
        await db.commit()  # keep the attempt count even though we reject
        raise AppError("INVALID_CODE", "That code is not correct")
    driver.verified_at, driver.whatsapp_opt_in = now, True
    driver.verification_code_hash = driver.verification_expires_at = None
    driver.verification_attempts = 0


async def verify(db: AsyncSession, p: Principal, driver_id: UUID, code: str) -> None:
    await confirm_verification(db, await get_scoped(db, p, driver_id), code)


async def import_csv(db: AsyncSession, p: Principal, file: UploadFile, dry_run: bool) -> ImportResult:
    _carrier(p)
    rows = await read_csv(file, ["driver_name", "phone", "licence_number"])
    errors: list[ImportError_] = []
    created, seen = 0, set()
    for n, row in rows:
        try:
            body = DriverIn(driver_name=row["driver_name"], phone=row["phone"], whatsapp_number=row.get("whatsapp_number") or None,
                            preferred_language=(row.get("preferred_language") or "en").lower(),
                            licence_number=row["licence_number"], home_base_city=row.get("home_base_city") or None)
            keys = {("p", body.phone), ("l", body.licence_number), *([("w", body.whatsapp_number)] if body.whatsapp_number else [])}
            if keys & seen:
                raise ValueError("Duplicate phone, licence or WhatsApp number inside the file")
            seen |= keys
            await _unique(db, body.phone, body.licence_number, body.whatsapp_number, None)
            if not dry_run:
                await create(db, p, body)
            created += 1
        except ValidationError as e:
            errors.append(ImportError_(row=n, message="; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())))
        except (ValueError, ValidationAppError, ConflictError) as e:
            errors.append(ImportError_(row=n, message=getattr(e, "message", str(e))))
    if errors and not dry_run:
        await db.rollback()
        return ImportResult(dry_run=False, created=0, errors=errors)
    return ImportResult(dry_run=dry_run, created=created, errors=errors)
