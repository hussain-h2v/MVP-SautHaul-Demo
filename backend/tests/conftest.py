import asyncio
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://setuhaul:setuhaul@postgres:5432/setuhaul")
TEST_DB = "setuhaul_test" + os.environ.get("TEST_DB_SUFFIX", "")
os.environ["DATABASE_URL"] = re.sub(r"/[^/]+$", "/" + TEST_DB, _base)
os.environ["ENV"] = "test"
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ.setdefault("PROVIDER_KEY_ENCRYPTION_KEY", "0" * 32)

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import Base, async_session_factory, engine  # noqa: E402
from app.core.idempotency import get_redis  # noqa: E402
from app.core.model_registry import import_all_models  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402

_SETTINGS: list[dict] = []
PASSWORD = "CorrectHorse-Battery9"
_HASH = hash_password(PASSWORD)
BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _recreate_db() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
    admin = re.sub(r"/[^/]+$", "/postgres", url)
    conn = await asyncpg.connect(admin)
    await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    await conn.execute(f"CREATE DATABASE {TEST_DB}")
    await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_recreate_db())
    subprocess.run(["alembic", "upgrade", "head"], cwd=BACKEND_DIR, check=True, capture_output=True)

    async def _snapshot() -> None:
        url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
        conn = await asyncpg.connect(url)
        _SETTINGS.extend(dict(r) for r in await conn.fetch("SELECT * FROM system_settings"))
        await conn.close()

    asyncio.run(_snapshot())


@pytest_asyncio.fixture(autouse=True)
async def clean() -> None:
    import_all_models()
    tables = [t.name for t in Base.metadata.sorted_tables]
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY"))
        for row in _SETTINGS:
            await conn.execute(
                text("INSERT INTO system_settings (id, key, value, description, created_at, updated_at, version) "
                     "VALUES (:id, :key, CAST(:value AS jsonb), :description, :created_at, :updated_at, :version)"),
                {**row, "value": __import__("json").dumps(row["value"]) if not isinstance(row["value"], str) else row["value"]},
            )
    redis = get_redis()
    try:
        keys = [k async for k in redis.scan_iter("rl:*")]
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
    finally:
        await redis.aclose()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@dataclass
class World:
    facility_a: object
    facility_b: object
    carrier_a: object
    carrier_b: object
    shipment_a: object
    shipment_b: object


@pytest_asyncio.fixture
async def world() -> World:
    from app.modules.carriers.models import Carrier
    from app.modules.drivers.models import Driver
    from app.modules.facilities.models import Facility
    from app.modules.shipments.models import Shipment
    from app.modules.users.models import User, UserScope
    from app.modules.vehicles.models import Vehicle, VehicleType
    from datetime import time

    now = datetime.now(UTC)
    async with async_session_factory() as db:
        fa = Facility(code="FAC-A", facility_name="Facility A", city="Jaipur", state="RJ",
                      open_time=time(6), close_time=time(22))
        fb = Facility(code="FAC-B", facility_name="Facility B", city="Gurgaon", state="HR",
                      open_time=time(7), close_time=time(21))
        ca = Carrier(code="CAR-A", carrier_name="Carrier A")
        cb = Carrier(code="CAR-B", carrier_name="Carrier B")
        vt = VehicleType(code="VT1", description="Truck", default_capacity_kg=10000, typical_dock_type="ANY")
        db.add_all([fa, fb, ca, cb, vt])
        await db.flush()
        shipments = []
        for tag, car, fac in (("A", ca, fa), ("B", cb, fb)):
            drv = Driver(code=f"DRV-{tag}", carrier_id=car.id, driver_name=f"Driver {tag}", phone=f"+91900000000{tag}",
                         licence_number=f"LIC-{tag}")
            veh = Vehicle(code=f"VEH-{tag}", carrier_id=car.id, vehicle_type_id=vt.id,
                          registration_number=f"RJ14-{tag}", capacity_kg=10000)
            db.add_all([drv, veh])
            await db.flush()
            s = Shipment(code=f"SHP-{tag}", order_reference=f"ORD-{tag}", carrier_id=car.id, driver_id=drv.id,
                         vehicle_id=veh.id, origin_name="Origin", origin_city="Delhi", destination_facility_id=fac.id,
                         customer_name="Cust", product_category="Goods", load_weight_kg=5000,
                         planned_departure_ts=now, original_eta_ts=now, expected_unload_min=60, current_status="ASSIGNED", offer_status="accepted")
            db.add(s)
            shipments.append(s)
        users = {
            "admin": User(email="admin@test.io", full_name="Admin", role="admin"),
            "planner": User(email="planner@test.io", full_name="Planner A", role="facility_planner"),
            "coordinator": User(email="coord@test.io", full_name="Coordinator", role="coordinator"),
            "carrier_a": User(email="carrier_a@test.io", full_name="Carrier A User", role="carrier_user"),
            "carrier_b": User(email="carrier_b@test.io", full_name="Carrier B User", role="carrier_user"),
        }
        for u in users.values():
            u.password_hash, u.status = _HASH, "active"
        db.add_all(users.values())
        await db.flush()
        db.add_all([
            UserScope(user_id=users["planner"].id, facility_id=fa.id),
            UserScope(user_id=users["carrier_a"].id, carrier_id=ca.id),
            UserScope(user_id=users["carrier_b"].id, carrier_id=cb.id),
        ])
        await db.commit()
        return World(fa, fb, ca, cb, shipments[0], shipments[1])


EMAILS = {
    "admin": "admin@test.io", "facility_planner": "planner@test.io", "coordinator": "coord@test.io",
    "carrier_user": "carrier_a@test.io", "carrier_b": "carrier_b@test.io",
}


async def login(client: AsyncClient, who: str):
    resp = await client.post("/api/v1/auth/login", json={"email": EMAILS[who], "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    return resp
