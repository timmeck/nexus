"""Tests for Adversarial Defense — Slashing, Escrow, Challenges, Sybil Detection."""

from __future__ import annotations

import pytest
from tests.conftest import create_agent


async def _ensure_all_tables():
    from nexus.federation.service import ensure_tables
    await ensure_tables()
    from nexus.payments.service import ensure_tables as pt
    await pt()
    from nexus.defense.service import ensure_tables as dt
    await dt()


# ── Slashing ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slash_agent(client, sample_agent_payload):
    """Should slash agent trust and credits."""
    await _ensure_all_tables()
    agent = await create_agent(client, sample_agent_payload())
    agent_id = agent["id"]

    resp = await client.post("/api/defense/slash", json={
        "agent_id": agent_id,
        "request_id": "test-req-001",
        "reason": "Bad output",
        "claimed_confidence": 0.95,
        "actual_quality": 0.1,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_after"] < data["trust_before"]
    assert data["reason"] == "Bad output"


@pytest.mark.asyncio
async def test_slashing_history(client, sample_agent_payload):
    """Should record slashing events."""
    await _ensure_all_tables()
    agent = await create_agent(client, sample_agent_payload())

    await client.post("/api/defense/slash", json={
        "agent_id": agent["id"],
        "request_id": "test-req-002",
        "reason": "Test slash",
        "claimed_confidence": 0.8,
        "actual_quality": 0.2,
    })

    resp = await client.get("/api/defense/slashes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["slashes"]) >= 1


# ── Escrow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_escrows_empty(client):
    """Should return empty list initially."""
    await _ensure_all_tables()
    resp = await client.get("/api/defense/escrows")
    assert resp.status_code == 200
    assert resp.json()["escrows"] == []


@pytest.mark.asyncio
async def test_release_mature_escrows(client):
    """Should handle no mature escrows."""
    await _ensure_all_tables()
    resp = await client.post("/api/defense/escrows/release-mature")
    assert resp.status_code == 200
    assert resp.json()["released"] == 0


# ── Challenges ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_challenge(client, sample_agent_payload):
    """Should create a challenge between agents."""
    await _ensure_all_tables()
    agent1 = await create_agent(client, sample_agent_payload())
    agent2 = await create_agent(client, sample_agent_payload())

    resp = await client.post("/api/defense/challenges", json={
        "request_id": "test-req-003",
        "challenger_id": agent1["id"],
        "target_id": agent2["id"],
        "reason": "Suspicious output",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["fee_paid"] > 0


@pytest.mark.asyncio
async def test_resolve_challenge_upheld(client, sample_agent_payload):
    """Resolving an upheld challenge should reward challenger and slash target."""
    await _ensure_all_tables()
    agent1 = await create_agent(client, sample_agent_payload())
    agent2 = await create_agent(client, sample_agent_payload())

    # Create challenge
    resp = await client.post("/api/defense/challenges", json={
        "request_id": "test-req-004",
        "challenger_id": agent1["id"],
        "target_id": agent2["id"],
        "reason": "Bad output detected",
    })
    challenge_id = resp.json()["challenge_id"]

    # Resolve as upheld
    resp = await client.post(f"/api/defense/challenges/{challenge_id}/resolve", json={
        "upheld": True,
        "ruling": "Output was indeed incorrect",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["upheld"] is True
    assert data["reward_paid"] > 0


@pytest.mark.asyncio
async def test_list_challenges(client, sample_agent_payload):
    """Should list challenges."""
    await _ensure_all_tables()
    resp = await client.get("/api/defense/challenges")
    assert resp.status_code == 200
    assert "challenges" in resp.json()


# ── Sybil Detection ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registration_rate(client):
    """Should check registration rate."""
    await _ensure_all_tables()
    resp = await client.get("/api/defense/sybil/rate")
    assert resp.status_code == 200
    data = resp.json()
    assert "registrations_last_hour" in data
    assert "rate_exceeded" in data


@pytest.mark.asyncio
async def test_agent_maturity(client, sample_agent_payload):
    """Should check if agent is mature enough."""
    await _ensure_all_tables()
    agent = await create_agent(client, sample_agent_payload())

    resp = await client.get(f"/api/defense/sybil/maturity/{agent['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mature"] is False  # New agent, no interactions
    assert data["interactions"] == 0


@pytest.mark.asyncio
async def test_sybil_clusters(client, sample_agent_payload):
    """Should detect similar agents."""
    await _ensure_all_tables()
    # Register agents with identical capabilities
    caps = [{"name": "sybil_test", "description": "Same cap", "languages": ["en"]}]
    for i in range(3):
        await create_agent(client, sample_agent_payload(
            name=f"sybil-{i}",
            capabilities=caps,
        ))

    resp = await client.get("/api/defense/sybil/clusters")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert data["clusters"][0]["count"] >= 2


@pytest.mark.asyncio
async def test_defense_stats(client):
    """Should return defense statistics."""
    await _ensure_all_tables()
    resp = await client.get("/api/defense/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_slashes" in data
    assert "escrows_held" in data
    assert "challenges_total" in data
