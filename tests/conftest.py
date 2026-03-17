"""Shared test fixtures for the Nexus test suite."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(autouse=True)
async def _isolate_db(tmp_path, monkeypatch):
    """Patch DB_PATH to a fresh temporary file for every test function.

    Also reset the database module's cached connection so each test starts clean.

    nexus.database imports DB_PATH and DATA_DIR at module level, so we must
    patch the names in *both* nexus.config and nexus.database.
    """
    from nexus.database import close_db

    # Close any leftover connection from a previous test.
    await close_db()

    db_file = tmp_path / f"test_nexus_{uuid.uuid4().hex[:8]}.db"

    # Patch in both modules so get_db() sees the test path.
    monkeypatch.setattr("nexus.config.DB_PATH", db_file)
    monkeypatch.setattr("nexus.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("nexus.database.DB_PATH", db_file)
    monkeypatch.setattr("nexus.database.DATA_DIR", tmp_path)

    # Ensure all tables exist (normally done by app lifespan)
    from nexus.database import get_db

    await get_db()  # creates core schema
    from nexus.defense.service import ensure_tables as defense_tables
    from nexus.federation.service import ensure_tables as federation_tables
    from nexus.payments.service import ensure_tables as payments_tables
    from nexus.policy.service import ensure_tables as policy_tables

    await payments_tables()
    await federation_tables()
    await defense_tables()
    await policy_tables()

    yield

    # Properly close the connection so aiosqlite threads don't leak.
    await close_db()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client wired to the FastAPI app via ASGI transport."""
    from nexus.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def sample_agent_payload():
    """Return a factory callable that produces unique AgentCreate dicts."""
    _counter = 0

    def _make(
        name: str | None = None,
        endpoint: str | None = None,
        capabilities: list | None = None,
        tags: list | None = None,
    ) -> dict:
        nonlocal _counter
        _counter += 1
        return {
            "name": name or f"test-agent-{_counter}",
            "description": f"Test agent number {_counter}",
            "endpoint": endpoint or f"http://localhost:{8000 + _counter}",
            "capabilities": capabilities or [],
            "tags": tags or [],
        }

    return _make


async def create_agent(client: AsyncClient, payload: dict) -> dict:
    """Helper: register an agent via the API and return the response JSON."""
    resp = await client.post("/api/registry/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()
