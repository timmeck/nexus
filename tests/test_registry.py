"""Tests for the Registry API (/api/registry)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_agent(client: AsyncClient, sample_agent_payload):
    """POST /api/registry/agents returns 201 with correct fields."""
    payload = sample_agent_payload(name="cortex")
    resp = await client.post("/api/registry/agents", json=payload)

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "cortex"
    assert data["endpoint"] == payload["endpoint"]
    assert data["status"] == "online"
    assert data["trust_score"] == 0.5
    assert "id" in data
    assert "registered_at" in data


@pytest.mark.asyncio
async def test_register_duplicate(client: AsyncClient, sample_agent_payload):
    """POST the same agent name twice returns 409."""
    payload = sample_agent_payload(name="duplicate-agent")
    resp1 = await client.post("/api/registry/agents", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/registry/agents", json=payload)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient, sample_agent_payload):
    """GET /api/registry/agents returns all registered agents."""
    await create_agent(client, sample_agent_payload(name="agent-a"))
    await create_agent(client, sample_agent_payload(name="agent-b"))

    resp = await client.get("/api/registry/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 2
    names = {a["name"] for a in agents}
    assert names == {"agent-a", "agent-b"}


@pytest.mark.asyncio
async def test_get_agent(client: AsyncClient, sample_agent_payload):
    """GET /api/registry/agents/{id} returns the correct agent."""
    created = await create_agent(client, sample_agent_payload(name="findme"))
    agent_id = created["id"]

    resp = await client.get(f"/api/registry/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "findme"


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient):
    """GET /api/registry/agents/{id} returns 404 for unknown ID."""
    resp = await client.get("/api/registry/agents/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_agent(client: AsyncClient, sample_agent_payload):
    """PATCH /api/registry/agents/{id} updates fields."""
    created = await create_agent(client, sample_agent_payload(name="updatable"))
    agent_id = created["id"]

    resp = await client.patch(
        f"/api/registry/agents/{agent_id}",
        json={"description": "updated description", "status": "degraded"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "updated description"
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_delete_agent(client: AsyncClient, sample_agent_payload):
    """DELETE /api/registry/agents/{id} removes the agent, subsequent GET returns 404."""
    created = await create_agent(client, sample_agent_payload(name="deletable"))
    agent_id = created["id"]

    resp = await client.delete(f"/api/registry/agents/{agent_id}")
    assert resp.status_code == 204

    resp2 = await client.get(f"/api/registry/agents/{agent_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat(client: AsyncClient, sample_agent_payload):
    """POST /api/registry/agents/{id}/heartbeat returns ok."""
    created = await create_agent(client, sample_agent_payload(name="heartbeat-agent"))
    agent_id = created["id"]

    resp = await client.post(f"/api/registry/agents/{agent_id}/heartbeat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_heartbeat_not_found(client: AsyncClient):
    """POST heartbeat for unknown agent returns 404."""
    resp = await client.post("/api/registry/agents/nonexistent/heartbeat")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_discover(client: AsyncClient, sample_agent_payload):
    """GET /api/registry/discover?capability=X finds agents with that capability."""
    payload = sample_agent_payload(
        name="legal-agent",
        capabilities=[
            {
                "name": "legal_analysis",
                "description": "Analyzes legal docs",
                "price_per_request": 1.0,
                "avg_response_ms": 3000,
            }
        ],
    )
    await create_agent(client, payload)

    # Also register one without the capability
    await create_agent(client, sample_agent_payload(name="plain-agent"))

    resp = await client.get("/api/registry/discover", params={"capability": "legal_analysis"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["capability"] == "legal_analysis"
    assert data["count"] == 1
    assert data["agents"][0]["name"] == "legal-agent"
