"""Tests for A2A Agent Card endpoints."""

from __future__ import annotations

import pytest

from tests.conftest import create_agent


@pytest.mark.asyncio
async def test_gateway_agent_card_empty(client):
    """Gateway card works with no agents — includes core 'verification' capability."""
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Nexus Protocol Gateway"
    assert data["protocol"] == "a2a/1.0"
    assert data["authentication"] == {"type": "bearer"}
    cap_names = [c["name"] for c in data["capabilities"]]
    assert "verification" in cap_names


@pytest.mark.asyncio
async def test_gateway_agent_card_dynamic_capabilities(client, sample_agent_payload):
    """Gateway card capabilities are populated from registered agents."""
    payload = sample_agent_payload(capabilities=[
        {"name": "text_generation", "price_per_request": 0.01},
        {"name": "code_analysis", "price_per_request": 0.05},
    ])
    await create_agent(client, payload)

    resp = await client.get("/.well-known/agent.json")
    data = resp.json()
    cap_names = [c["name"] for c in data["capabilities"]]
    assert "text_generation" in cap_names
    assert "code_analysis" in cap_names
    assert "verification" in cap_names


@pytest.mark.asyncio
async def test_per_agent_card(client, sample_agent_payload):
    """Per-agent card returns correct agent details."""
    payload = sample_agent_payload(capabilities=[
        {"name": "summarization", "price_per_request": 0.02},
    ])
    agent = await create_agent(client, payload)
    agent_id = agent["id"]

    resp = await client.get(f"/api/agents/{agent_id}/card")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == agent["name"]
    assert data["protocol"] == "a2a/1.0"
    assert data["nexus"]["agent_id"] == agent_id
    assert len(data["capabilities"]) == 1
    assert data["capabilities"][0]["name"] == "summarization"


@pytest.mark.asyncio
async def test_per_agent_card_not_found(client):
    """Per-agent card returns 404 for unknown agent."""
    resp = await client.get("/api/agents/nonexistent/card")
    assert resp.status_code == 404
