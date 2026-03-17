"""Tests for the Trust API (/api/trust)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_trust_report_not_found(client: AsyncClient):
    """GET /api/trust/report/{id} returns 404 for unknown agent."""
    resp = await client.get("/api/trust/report/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trust_history_empty(client: AsyncClient, sample_agent_payload):
    """GET /api/trust/history/{id} returns an empty list when no interactions exist."""
    created = await create_agent(client, sample_agent_payload(name="lonely-agent"))
    agent_id = created["id"]

    resp = await client.get(f"/api/trust/history/{agent_id}")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_record_and_report(client: AsyncClient, sample_agent_payload):
    """Register an agent, record interactions via trust service, verify the trust report."""
    created = await create_agent(client, sample_agent_payload(name="trust-agent"))
    agent_id = created["id"]

    # Record interactions directly via the service layer
    from nexus.trust.service import record_interaction

    await record_interaction(
        request_id="req-001",
        consumer_id="consumer-x",
        provider_id=agent_id,
        success=True,
        confidence=0.9,
        cost=1.5,
        response_ms=200,
    )
    await record_interaction(
        request_id="req-002",
        consumer_id="consumer-y",
        provider_id=agent_id,
        success=False,
        confidence=0.3,
        cost=0.5,
        response_ms=500,
    )

    # Fetch trust report via API
    resp = await client.get(f"/api/trust/report/{agent_id}")
    assert resp.status_code == 200
    report = resp.json()

    assert report["agent_id"] == agent_id
    assert report["agent_name"] == "trust-agent"
    assert report["total_interactions"] == 2
    assert report["successful_interactions"] == 1
    assert report["success_rate"] == 0.5
    assert report["avg_confidence"] == pytest.approx(0.6, abs=0.01)
    assert report["avg_response_ms"] == pytest.approx(350.0, abs=1.0)
    assert report["total_earned"] == pytest.approx(2.0, abs=0.01)

    # Trust score should have changed from initial 0.5
    # +0.05 for success, -0.10 for failure => 0.5 + 0.05 - 0.10 = 0.45
    assert report["trust_score"] == pytest.approx(0.45, abs=0.01)

    # Verify history via API
    resp2 = await client.get(f"/api/trust/history/{agent_id}")
    assert resp2.status_code == 200
    history = resp2.json()
    assert len(history) == 2

    # Verify trust ledger — append-only delta log
    resp3 = await client.get(f"/api/trust/ledger/{agent_id}")
    assert resp3.status_code == 200
    ledger = resp3.json()
    assert len(ledger) == 2

    # Most recent entry first (DESC order)
    latest = ledger[0]
    assert latest["agent_id"] == agent_id
    assert latest["reason"] == "failure"
    assert latest["delta"] < 0
    assert "trust_before" in latest
    assert "trust_after" in latest
    assert latest["request_id"] == "req-002"

    # Older entry
    first = ledger[1]
    assert first["reason"] == "success"
    assert first["delta"] > 0
    assert first["request_id"] == "req-001"
