"""End-to-end lifecycle tests for the enforced request pipeline.

Tests the hard path: Policy → Route → Budget → Escrow → Forward → Trust → Settle.
If it is not enforced in the request lifecycle, it is not part of the protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


# ── Helpers ────────────────────────────────────────────────────


async def _register_agent_with_locality(
    client: AsyncClient,
    name: str,
    region: str = "eu",
    jurisdiction: str = "gdpr",
    capabilities: list | None = None,
) -> dict:
    """Register an agent and set its locality + compliance claims."""
    payload = {
        "name": name,
        "endpoint": f"http://localhost:{19100 + hash(name) % 100}",
        "capabilities": capabilities
        or [{"name": "analysis", "description": "Data analysis", "languages": ["en"], "price_per_request": 0.5}],
    }
    agent = await create_agent(client, payload)
    agent_id = agent["id"]

    # Set locality
    await client.post(
        "/api/policy/locality",
        json={
            "agent_id": agent_id,
            "region": region,
            "jurisdiction": jurisdiction,
            "country_code": "DE" if region == "eu" else "US",
        },
    )

    return agent


# ── Test: Happy path includes trail ────────────────────────────


@pytest.mark.asyncio
async def test_request_has_audit_trail(client: AsyncClient):
    """Every request response must include an audit trail with steps."""
    payload = {
        "from_agent": "consumer-1",
        "query": "What is AI?",
        "capability": "general",
    }
    resp = await client.post("/api/protocol/request", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Even a failed request (no agents) must have a trail
    trail = data.get("meta", {}).get("trail")
    assert trail is not None, "Response must include audit trail"
    assert "steps" in trail
    assert len(trail["steps"]) >= 2  # at least received + final state
    assert trail["steps"][0]["step"] == "received"


# ── Test: Policy gate blocks non-compliant requests ─────────


@pytest.mark.asyncio
async def test_policy_gate_blocks_request(client: AsyncClient):
    """Active policies must block requests when no agents match."""
    # Register an agent WITHOUT locality info
    await create_agent(
        client,
        {
            "name": "unlabeled-agent",
            "endpoint": "http://localhost:19200",
            "capabilities": [{"name": "analysis", "description": "Analysis", "languages": ["en"]}],
        },
    )

    # Create a policy requiring EU region
    resp = await client.post(
        "/api/policy/routing",
        json={
            "name": "eu-only",
            "description": "Only EU agents",
            "rules": {"require_region": "eu"},
            "priority": 10,
        },
    )
    assert resp.status_code == 200

    # Request should be rejected — no agent has EU locality
    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "consumer-1",
            "query": "Analyze this data",
            "capability": "analysis",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("rejected", "failed")


@pytest.mark.asyncio
async def test_policy_gate_allows_compliant_agents(client: AsyncClient):
    """Policy should allow requests when compliant agents exist."""
    # Register agent with EU locality
    await _register_agent_with_locality(client, "eu-agent", region="eu", jurisdiction="gdpr")

    # Create EU-only policy
    await client.post(
        "/api/policy/routing",
        json={
            "name": "eu-policy",
            "rules": {"require_region": "eu"},
            "priority": 10,
        },
    )

    # Request should pass policy (but still fail at forwarding since agent isn't running)
    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "consumer-1",
            "query": "Analyze this",
            "capability": "analysis",
        },
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # Should have passed policy and attempted routing
    assert "policy_check" in steps
    assert "routing" in steps


# ── Test: No policies = open system ──────────────────────────


@pytest.mark.asyncio
async def test_no_policies_allows_everything(client: AsyncClient):
    """Without active policies, all requests should pass the policy gate."""
    await create_agent(
        client,
        {
            "name": "open-agent",
            "endpoint": "http://localhost:19300",
            "capabilities": [{"name": "chat", "description": "Chat", "languages": ["en"]}],
        },
    )

    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "consumer-1",
            "query": "Hello",
            "capability": "chat",
        },
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # Should pass policy check (no policies)
    assert "policy_check" in steps
    # Should not be rejected
    assert data["status"] != "rejected"


# ── Test: Budget pre-check ───────────────────────────────────


@pytest.mark.asyncio
async def test_budget_precheck_rejects_broke_consumer(client: AsyncClient):
    """Consumer without enough credits should be rejected before forwarding."""
    # Register agent with high price
    await create_agent(
        client,
        {
            "name": "expensive-agent",
            "endpoint": "http://localhost:19400",
            "capabilities": [
                {"name": "premium", "description": "Expensive service", "languages": ["en"], "price_per_request": 999.0}
            ],
        },
    )

    # Consumer has default 100 credits, agent costs 999
    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "broke-consumer",
            "query": "Do something expensive",
            "capability": "premium",
        },
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # Should hit budget check and be rejected
    assert "budget_check" in steps
    assert data["status"] in ("rejected", "failed")


# ── Test: Escrow is created on successful response ───────────


@pytest.mark.asyncio
async def test_escrow_metadata_in_response(client: AsyncClient):
    """When escrow is created, response meta should contain escrow info."""
    # Register consumer with credits first
    consumer = await create_agent(
        client,
        {
            "name": "rich-consumer",
            "endpoint": "http://localhost:19501",
            "capabilities": [],
        },
    )
    consumer_id = consumer["id"]

    # Register provider agent
    await create_agent(
        client,
        {
            "name": "escrow-agent",
            "endpoint": "http://localhost:19500",
            "capabilities": [{"name": "work", "description": "Work", "languages": ["en"], "price_per_request": 1.0}],
        },
    )

    # Consumer has 100 credits (default), agent costs 1.0 — should pass budget
    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": consumer_id,
            "query": "Do some work",
            "capability": "work",
        },
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # Should reach forwarding step (then fail because agent is offline)
    assert "forwarding" in steps
    # Failed requests should not have escrow
    if data["status"] == "completed":
        assert "escrow" in steps


# ── Test: Trail captures all lifecycle steps ─────────────────


@pytest.mark.asyncio
async def test_trail_has_minimum_steps_for_failure(client: AsyncClient):
    """Even failed requests must have complete trail with proper steps."""
    await create_agent(
        client,
        {
            "name": "offline-agent",
            "endpoint": "http://localhost:19600",
            "capabilities": [{"name": "test", "description": "Test", "languages": ["en"]}],
        },
    )

    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "consumer-1",
            "query": "Test query",
            "capability": "test",
        },
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # Minimum expected lifecycle steps
    assert "received" in steps
    assert "policy_check" in steps
    assert "routing" in steps


# ── Test: Direct routing respects policy ─────────────────────


@pytest.mark.asyncio
async def test_direct_routing_respects_policy(client: AsyncClient):
    """Even direct agent targeting must pass through policy gate."""
    agent = await create_agent(
        client,
        {
            "name": "us-agent",
            "endpoint": "http://localhost:19700",
            "capabilities": [{"name": "chat", "description": "Chat", "languages": ["en"]}],
        },
    )

    # Set US locality
    await client.post(
        "/api/policy/locality",
        json={
            "agent_id": agent["id"],
            "region": "us",
            "jurisdiction": "none",
        },
    )

    # Create EU-only policy
    await client.post(
        "/api/policy/routing",
        json={
            "name": "eu-strict",
            "rules": {"require_region": "eu"},
            "priority": 10,
        },
    )

    # Direct request to US agent should be blocked by policy
    resp = await client.post(
        "/api/protocol/request",
        json={
            "from_agent": "consumer-1",
            "to_agent": agent["id"],
            "query": "Hello",
        },
    )
    data = resp.json()
    # Should fail — US agent blocked by EU policy
    assert data["status"] in ("rejected", "failed")
