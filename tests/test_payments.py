"""Tests for Micropayments — wallets, transactions, budget checks."""

from __future__ import annotations

import pytest
from tests.conftest import create_agent


async def _ensure_tables():
    from nexus.federation.service import ensure_tables
    await ensure_tables()
    from nexus.payments.service import ensure_tables as ensure_payment_tables
    await ensure_payment_tables()


@pytest.mark.asyncio
async def test_wallet_created_on_registration(client, sample_agent_payload):
    """Registering an agent should auto-create a wallet."""
    await _ensure_tables()
    payload = sample_agent_payload()
    agent = await create_agent(client, payload)
    agent_id = agent["id"]

    resp = await client.get(f"/api/payments/wallets/{agent_id}")
    assert resp.status_code == 200
    wallet = resp.json()
    assert wallet["agent_id"] == agent_id
    assert wallet["balance"] == 100.0


@pytest.mark.asyncio
async def test_top_up(client, sample_agent_payload):
    """Should be able to add credits to a wallet."""
    await _ensure_tables()
    agent = await create_agent(client, sample_agent_payload())
    agent_id = agent["id"]

    resp = await client.post(f"/api/payments/wallets/{agent_id}/topup", json={
        "agent_id": agent_id,
        "amount": 50.0,
        "reason": "test top-up",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 150.0


@pytest.mark.asyncio
async def test_list_wallets(client, sample_agent_payload):
    """Should list all wallets."""
    await _ensure_tables()
    await create_agent(client, sample_agent_payload())
    await create_agent(client, sample_agent_payload())

    resp = await client.get("/api/payments/wallets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 2


@pytest.mark.asyncio
async def test_payment_stats(client):
    """Should return payment statistics."""
    await _ensure_tables()

    resp = await client.get("/api/payments/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "wallets" in data
    assert "total_credits_in_circulation" in data
    assert "total_transactions" in data


@pytest.mark.asyncio
async def test_balance_check(client, sample_agent_payload):
    """Should check agent balance."""
    await _ensure_tables()
    agent = await create_agent(client, sample_agent_payload())
    agent_id = agent["id"]

    resp = await client.get(f"/api/payments/wallets/{agent_id}/balance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 100.0


@pytest.mark.asyncio
async def test_transaction_history_empty(client, sample_agent_payload):
    """New agent should have empty transaction history."""
    await _ensure_tables()
    agent = await create_agent(client, sample_agent_payload())
    agent_id = agent["id"]

    resp = await client.get(f"/api/payments/transactions/{agent_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
