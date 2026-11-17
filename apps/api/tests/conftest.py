import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://setuhaul:setuhaul@localhost:5432/setuhaul_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("PROVIDER_KEY_ENCRYPTION_KEY", "0" * 32)

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
