"""Tests for agent registration with auth — API keys and HMAC integration."""

from __future__ import annotations

import pytest

from tests.conftest import create_agent


@pytest.mark.asyncio
async def test_register_returns_api_key(client, sample_agent_payload):
    """Registration should return an API key."""
    payload = sample_agent_payload()
    resp = await client.post("/api/registry/agents", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "api_key" in data
    assert data["api_key"].startswith("nxs_")
    assert data["auth_enabled"] is True


@pytest.mark.asyncio
async def test_list_hides_api_key(client, sample_agent_payload):
    """Public agent listing should mask API keys."""
    payload = sample_agent_payload()
    reg = await client.post("/api/registry/agents", json=payload)
    full_key = reg.json()["api_key"]

    resp = await client.get("/api/registry/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) >= 1

    agent = agents[0]
    assert agent["api_key"] != full_key  # Should be masked
    assert "..." in agent["api_key"]


@pytest.mark.asyncio
async def test_get_agent_hides_api_key(client, sample_agent_payload):
    """Getting single agent should mask API key."""
    payload = sample_agent_payload()
    reg = await client.post("/api/registry/agents", json=payload)
    agent_id = reg.json()["id"]
    full_key = reg.json()["api_key"]

    resp = await client.get(f"/api/registry/agents/{agent_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_key"] != full_key
    assert "..." in data["api_key"]


async def _ensure_all_tables():
    """Ensure all extra tables exist for stats tests."""
    from nexus.defense.service import ensure_tables as dt
    from nexus.federation.service import ensure_tables
    from nexus.payments.service import ensure_tables as pt
    from nexus.policy.service import ensure_tables as pol

    await ensure_tables()
    await pt()
    await dt()
    await pol()


@pytest.mark.asyncio
async def test_stats_includes_auth_count(client, sample_agent_payload):
    """Stats should show how many agents have auth enabled."""
    await _ensure_all_tables()

    payload = sample_agent_payload()
    await create_agent(client, payload)

    resp = await client.get("/api/stats")
    data = resp.json()
    assert "agents_auth_enabled" in data
    assert data["agents_auth_enabled"] >= 1


@pytest.mark.asyncio
async def test_stats_includes_verification_count(client):
    """Stats should include verification counts."""
    await _ensure_all_tables()

    resp = await client.get("/api/stats")
    data = resp.json()
    assert "verifications_total" in data
    assert "verifications_consensus" in data
