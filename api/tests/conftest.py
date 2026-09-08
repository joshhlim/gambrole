"""Integration test fixtures: a real Postgres test database (not mocked),
and helpers for simulating several authenticated "devices" in one test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "api"))

# Must happen before any `app.*` import, since Settings() reads the env at
# construction time (module-level `engine` in app.db is built from it).
os.environ.setdefault(
    "TAIDI_DATABASE_URL", "postgresql+asyncpg://gambrole:gambrole_dev@localhost:5433/gambrole_test"
)

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from app.auth import mint_dev_token  # noqa: E402
from app.db import engine, metadata  # noqa: E402
from app.main import app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

_ADMIN_DSN = "postgresql://gambrole:gambrole_dev@localhost:5433/gambrole"
_TEST_DB = "gambrole_test"


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database():
    import asyncio

    async def _create():
        conn = await asyncpg.connect(_ADMIN_DSN)
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{_TEST_DB}"')
        finally:
            await conn.close()

    asyncio.run(_create())


@pytest_asyncio.fixture(autouse=True)
async def _clean_schema():
    """Fresh tables for every test — cheap since the schema is tiny.

    Disposing the engine first rebinds its connection pool to the CURRENT
    test's event loop — pytest-asyncio gives each test function its own
    loop by default, and asyncpg connections can't be reused across loops.
    """
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class Device:
    """One authenticated "device": an httpx client pre-armed with one
    player's bearer token, so tests read like `alice.post(...)`."""

    def __init__(self, http_client: AsyncClient, token: str, user_id: str, display_name: str):
        self._client = http_client
        self.user_id = user_id
        self.display_name = display_name
        self._headers = {"Authorization": f"Bearer {token}"}

    async def get(self, url: str, **kw):
        return await self._client.get(url, headers=self._headers, **kw)

    async def post(self, url: str, **kw):
        return await self._client.post(url, headers=self._headers, **kw)


@pytest_asyncio.fixture
async def make_device(client: AsyncClient):
    async def _make(display_name: str) -> Device:
        token, uid = mint_dev_token(display_name)
        return Device(client, token, str(uid), display_name)

    return _make
