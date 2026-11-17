"""Shared builders and invariant checks for the Milestone 4 booking-engine tests."""
import itertools
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import async_session_factory
from app.main import app
from app.modules.appointments.models import Appointment
from app.modules.booking.models import SlotClaim
from app.modules.docks.models import Dock
from app.modules.drivers.models import Driver
from app.modules.facilities.models import FacilityRule
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.vehicles.models import Vehicle, VehicleType
from tests.conftest import login

IST = ZoneInfo("Asia/Kolkata")
DAY = datetime.now(IST).date() + timedelta(days=30)
ACTIVE = ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS")
_seq = itertools.count(1)


def at(hm: str, day_offset: int = 0) -> datetime:
    """DAY + offset at HH:MM IST, as UTC."""
    h, m = map(int, hm.split(":"))
    return datetime.combine(DAY + timedelta(days=day_offset), time(h, m), tzinfo=IST).astimezone(UTC)


@dataclass
class M4:
    fac: object
    carrier: object
    vt: object
    docks: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)

    def slot(self, dock: str, hm: str, day_offset: int = 0):
        return self.slots[(dock, hm, day_offset)]

    def ids(self, dock: str, *hms: str, day_offset: int = 0) -> list[str]:
        return [str(self.slot(dock, hm, day_offset).id) for hm in hms]


async def _mk_slot(db, fac, dock, start, end) -> AppointmentSlot:
    s = AppointmentSlot(code=f"{dock.code}-{start.astimezone(IST):%y%m%d%H%M}", facility_id=fac.id, dock_id=dock.id,
                        slot_start_ts=start, slot_end_ts=end)
    db.add(s)
    return s


async def build_m4(world, days: int = 2) -> M4:
    """Docks D1, D2 (STANDARD), R1 (REEFER, 60-min slots) and H1 (HEAVY, 90-min slots) on facility A."""
    async with async_session_factory() as db:
        vt2 = VehicleType(code="VT2", description="Other truck", default_capacity_kg=8000, typical_dock_type="ANY")
        db.add(vt2)
        specs = {"D1": ("STANDARD", 30000), "D2": ("STANDARD", 30000), "R1": ("REEFER", 30000), "H1": ("HEAVY", 60000)}
        docks = {}
        for code, (dtype, cap) in specs.items():
            d = Dock(code=f"{world.facility_a.code}-{code}", facility_id=world.facility_a.id, dock_code=code,
                     dock_type=dtype, supports_refrigerated=dtype == "REEFER", max_vehicle_weight_kg=cap)
            db.add(d)
            docks[code] = d
        await db.flush()
        slots = {}
        for off in range(days):
            for code, d in docks.items():
                step = 90 if d.dock_type == "HEAVY" else 60
                cur = datetime.combine(DAY + timedelta(days=off), time(8, 0), tzinfo=IST)
                limit = datetime.combine(DAY + timedelta(days=off), time(22, 0), tzinfo=IST)
                while cur + timedelta(minutes=step) <= limit:
                    s = await _mk_slot(db, world.facility_a, d, cur.astimezone(UTC), (cur + timedelta(minutes=step)).astimezone(UTC))
                    slots[(code, cur.strftime("%H:%M"), off)] = s
                    cur += timedelta(minutes=step)
        await db.commit()
        out = M4(fac=world.facility_a, carrier=world.carrier_a, vt=vt2)
        out.docks = {k: SimpleNamespace(id=d.id, code=d.code, dock_code=d.dock_code) for k, d in docks.items()}
        out.slots = {k: SimpleNamespace(id=s.id, start=s.slot_start_ts, end=s.slot_end_ts, code=s.code) for k, s in slots.items()}
        return out


@pytest_asyncio.fixture
async def m4(world) -> M4:
    return await build_m4(world)


async def new_shipment(world, tag: str, *, weight: int = 5000, dock_type: str = "ANY", temp: bool = False,
                       priority: str = "NORMAL", unload: int = 60, eta: datetime | None = None,
                       vehicle_type_code: str = "VT1", status: str = "ASSIGNED") -> SimpleNamespace:
    n = next(_seq)
    eta = eta or at("07:00")
    async with async_session_factory() as db:
        vt = (await db.execute(text("SELECT id FROM vehicle_types WHERE code = :c"), {"c": vehicle_type_code})).scalar_one()
        drv = Driver(code=f"M4D{n}", carrier_id=world.carrier_a.id, driver_name=f"M4 Driver {tag}", phone=f"+9188{n:08d}",
                     licence_number=f"M4LIC{n}")
        db.add(drv)
        await db.flush()
        veh = Vehicle(code=f"M4V{n}", carrier_id=world.carrier_a.id, vehicle_type_id=vt, registration_number=f"M4-{n}",
                      capacity_kg=20000, refrigeration_capable=temp)
        db.add(veh)
        await db.flush()
        s = Shipment(code=f"M4-{tag}", order_reference=f"M4-ORD-{tag}-{n}", carrier_id=world.carrier_a.id, driver_id=drv.id,
                     vehicle_id=veh.id, origin_name="Origin", origin_city="Delhi",
                     destination_facility_id=world.facility_a.id, customer_name="Cust", product_category="Goods",
                     load_weight_kg=weight, required_dock_type=dock_type, temperature_control_required=temp,
                     priority_code=priority, planned_departure_ts=eta - timedelta(hours=6), original_eta_ts=eta,
                     expected_unload_min=unload, current_status=status, offer_status="accepted")
        db.add(s)
        await db.commit()
        return SimpleNamespace(id=s.id, code=s.code, driver_id=drv.id)


async def add_rule(world, rule_type: str, value: str) -> None:
    async with async_session_factory() as db:
        db.add(FacilityRule(facility_id=world.facility_a.id, rule_type=rule_type, rule_value=value,
                            description=f"{rule_type} for tests", effective_from=date(2026, 1, 1)))
        await db.commit()


async def orm_book(shipment_id: UUID, slot_id: UUID, status: str = "CONFIRMED", code: str | None = None,
                   booked_at: datetime | None = None) -> UUID:
    """Appointment + its active claim, written like the engine would (for scenarios needing past slots)."""
    async with async_session_factory() as db:
        a = Appointment(code=code or f"ORM{next(_seq)}", shipment_id=shipment_id, slot_id=slot_id, appointment_status=status,
                        booking_source="PLANNER", booked_at=booked_at or datetime.now(UTC))
        db.add(a)
        await db.flush()
        db.add(SlotClaim(slot_id=slot_id, appointment_id=a.id, active=True))
        await db.commit()
        return a.id


@asynccontextmanager
async def session(who: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await login(c, who)
        yield c


async def clone_clients(client: AsyncClient, n: int) -> list[AsyncClient]:
    """n independent clients (own connection state) re-using an already authenticated cookie jar."""
    out = []
    for _ in range(n):
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=client.cookies,
                        headers={"X-CSRF-Token": client.headers["X-CSRF-Token"]})
        out.append(c)
    return out


async def close_all(clients: list[AsyncClient]) -> None:
    for c in clients:
        await c.aclose()


async def assert_invariants(db=None) -> None:
    """The capacity invariants that must hold after every step (spec section 3 / 15)."""
    own = db is None
    db = db or async_session_factory()
    if own:
        db = await db.__aenter__()
    try:
        async def rows(sql: str):
            return [tuple(r) for r in (await db.execute(text(sql))).all()]

        assert await rows("SELECT slot_id FROM slot_claims WHERE active GROUP BY slot_id HAVING count(*) > 1") == [], \
            "a slot has more than one active claim"
        assert await rows("SELECT slot_id FROM appointments WHERE appointment_status IN "
                          "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') GROUP BY slot_id HAVING count(*) > 1") == [], \
            "a slot has more than one active appointment"
        assert await rows("SELECT slot_id FROM slot_holds WHERE status = 'active' GROUP BY slot_id HAVING count(*) > 1") == [], \
            "a slot has more than one active hold"
        assert await rows("SELECT shipment_id FROM slot_holds WHERE status = 'active' GROUP BY shipment_id HAVING count(*) > 1") == [], \
            "a shipment has more than one active hold"
        assert await rows("SELECT shipment_id FROM appointments WHERE is_current AND appointment_status IN "
                          "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') GROUP BY shipment_id HAVING count(*) > 1") == [], \
            "a shipment has more than one current active appointment"
        assert await rows("SELECT a.id FROM appointments a WHERE a.appointment_status IN "
                          "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') AND NOT EXISTS "
                          "(SELECT 1 FROM slot_claims c WHERE c.appointment_id = a.id AND c.active)") == [], \
            "an active appointment has no claim"
        assert await rows("SELECT c.id FROM slot_claims c JOIN appointments a ON a.id = c.appointment_id WHERE c.active "
                          "AND a.appointment_status NOT IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')") == [], \
            "an ended appointment still holds a claim"
        assert await rows("SELECT c.id FROM slot_claims c JOIN slot_holds h ON h.id = c.hold_id WHERE c.active "
                          "AND h.status <> 'active'") == [], "a closed hold still holds a claim"
        for hid, slot_id, extra in await rows("SELECT id, slot_id, extra_slot_ids FROM slot_holds WHERE status = 'active'"):
            want = {slot_id, *[UUID(x) for x in extra]}
            got = {r[0] for r in await rows(f"SELECT slot_id FROM slot_claims WHERE active AND hold_id = '{hid}'")}
            assert want == got, f"hold {hid} claims {got} != its slots {want}"
    finally:
        if own:
            await db.__aexit__(None, None, None)


async def scalar(sql: str, **params):
    async with async_session_factory() as db:
        return (await db.execute(text(sql), params)).scalar_one()


async def rows(sql: str, **params):
    async with async_session_factory() as db:
        return [tuple(r) for r in (await db.execute(text(sql), params)).all()]
