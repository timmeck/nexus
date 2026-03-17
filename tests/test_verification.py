"""Tests for Multi-Agent Verification."""

from __future__ import annotations

import pytest

from tests.conftest import create_agent


@pytest.mark.asyncio
async def test_verify_not_enough_agents(client, sample_agent_payload):
    """Verification should fail gracefully when not enough agents."""
    resp = await client.post(
        "/api/protocol/verify",
        json={
            "query": "What is 2+2?",
            "capability": "math",
            "min_agents": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["consensus"] is False
    assert data["agents_queried"] == 0
    assert "Not enough agents" in data["best_answer"]


@pytest.mark.asyncio
async def test_verify_with_agents_offline(client, sample_agent_payload):
    """Verification with registered but offline agents should handle errors."""
    # Register 3 agents with same capability
    for i in range(3):
        payload = sample_agent_payload(
            name=f"math-agent-{i}",
            endpoint=f"http://localhost:{19000 + i}",
            capabilities=[
                {
                    "name": "math",
                    "description": "Math operations",
                    "languages": ["en"],
                }
            ],
        )
        await create_agent(client, payload)

    resp = await client.post(
        "/api/protocol/verify",
        json={
            "query": "What is 2+2?",
            "capability": "math",
            "min_agents": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Agents are not actually running, so all should fail
    assert data["agents_queried"] == 3
    assert len(data["answers"]) == 3
    for answer in data["answers"]:
        assert answer["status"] in ("failed", "timeout")


@pytest.mark.asyncio
async def test_list_verifications(client):
    """Should be able to list verification history."""
    # First do a verification
    await client.post(
        "/api/protocol/verify",
        json={
            "query": "test query",
            "capability": "test",
            "min_agents": 2,
        },
    )

    resp = await client.get("/api/protocol/verifications")
    assert resp.status_code == 200
    data = resp.json()
    assert "verifications" in data
    assert data["count"] >= 1
    assert data["verifications"][0]["query"] == "test query"


@pytest.mark.asyncio
async def test_verify_stores_result(client):
    """Verification results should be persisted."""
    await client.post(
        "/api/protocol/verify",
        json={
            "query": "stored query",
            "capability": "test",
            "min_agents": 2,
        },
    )

    resp = await client.get("/api/protocol/verifications")
    data = resp.json()
    found = any(v["query"] == "stored query" for v in data["verifications"])
    assert found


@pytest.mark.asyncio
async def test_verify_min_agents_validation(client):
    """min_agents must be at least 2."""
    resp = await client.post(
        "/api/protocol/verify",
        json={
            "query": "test",
            "capability": "test",
            "min_agents": 1,
        },
    )
    assert resp.status_code == 422  # Pydantic validation error
