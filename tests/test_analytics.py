"""Tests for Analytics API endpoints."""

from __future__ import annotations

import pytest

from tests.conftest import create_agent


@pytest.mark.asyncio
async def test_request_analytics_empty(client):
    """Request analytics returns empty data when no interactions exist."""
    resp = await client.get("/api/analytics/requests")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_type"] == "day"
    assert data["periods"] == []
    assert data["totals"]["total"] == 0


@pytest.mark.asyncio
async def test_request_analytics_hour_period(client):
    """Request analytics accepts hour period parameter."""
    resp = await client.get("/api/analytics/requests?period=hour")
    assert resp.status_code == 200
    assert resp.json()["period_type"] == "hour"


@pytest.mark.asyncio
async def test_agent_analytics_empty(client):
    """Agent analytics returns empty list when no interactions exist."""
    resp = await client.get("/api/analytics/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents"] == []
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_cost_analytics_empty(client):
    """Cost analytics returns zeros when no paid interactions exist."""
    resp = await client.get("/api/analytics/costs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["by_agent"] == []
    assert data["totals"]["total_cost"] == 0


@pytest.mark.asyncio
async def test_agent_analytics_with_interaction(client, sample_agent_payload):
    """Agent analytics reflect recorded interactions."""
    payload = sample_agent_payload(capabilities=[{"name": "test_cap"}])
    agent = await create_agent(client, payload)

    # Insert a fake interaction directly
    from nexus.database import get_db

    db = await get_db()
    await db.execute(
        """INSERT INTO interactions
           (interaction_id, request_id, consumer_id, provider_id,
            success, confidence, cost, response_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("int-1", "req-1", "consumer-1", agent["id"], 1, 0.9, 0.05, 150, "2026-03-20T10:00:00"),
    )
    await db.execute(
        """INSERT INTO interactions
           (interaction_id, request_id, consumer_id, provider_id,
            success, confidence, cost, response_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("int-2", "req-2", "consumer-1", agent["id"], 0, 0.0, 0.0, 500, "2026-03-20T11:00:00"),
    )
    await db.commit()

    # Check agent analytics
    resp = await client.get("/api/analytics/agents")
    data = resp.json()
    assert data["count"] == 1
    agent_stat = data["agents"][0]
    assert agent_stat["agent_id"] == agent["id"]
    assert agent_stat["total_requests"] == 2
    assert agent_stat["successful"] == 1
    assert agent_stat["failed"] == 1
    assert agent_stat["error_rate"] == 0.5

    # Check request analytics
    resp = await client.get("/api/analytics/requests?period=day")
    data = resp.json()
    assert data["totals"]["total"] == 2

    # Check cost analytics
    resp = await client.get("/api/analytics/costs")
    data = resp.json()
    assert data["totals"]["paid_requests"] == 1
    assert data["totals"]["total_cost"] == 0.05
