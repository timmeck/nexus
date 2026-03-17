"""Adversarial invariant tests — prove enforcement holds under pressure.

These are the "böse Tests" that ChatGPT demanded:
1. Policy reject blocks dispatch GUARANTEED
2. Provider failure triggers NO settlement
3. Illegal state transitions throw HARD
4. Stale heartbeat agents are NOT routed
5. Audit trail covers complete lifecycle
6. Budget check prevents dispatch to unaffordable agents
7. No settlement path bypasses escrow (fallback removed)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


# ── 1. Policy rejection is absolute ─────────────────────────


@pytest.mark.asyncio
async def test_policy_reject_blocks_all_dispatch(client: AsyncClient):
    """Even with a perfect agent available, policy rejection must block dispatch.

    Invariant: No forwarding step in trail when policy rejects.
    """
    # Register perfect agent with locality
    agent = await create_agent(
        client,
        {
            "name": "perfect-agent",
            "endpoint": "http://localhost:19800",
            "capabilities": [{"name": "analysis", "description": "Analysis", "languages": ["en"]}],
        },
    )

    # Set US locality
    await client.post(
        "/api/policy/locality",
        json={"agent_id": agent["id"], "region": "us", "jurisdiction": "none"},
    )

    # Create EU-only policy
    await client.post(
        "/api/policy/routing",
        json={"name": "eu-strict-inv", "rules": {"require_region": "eu"}, "priority": 100},
    )

    # Request — should be blocked BEFORE any routing/forwarding happens
    resp = await client.post(
        "/api/protocol/request",
        json={"from_agent": "consumer-1", "query": "test", "capability": "analysis"},
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # INVARIANT: forwarding must NEVER appear after policy rejection
    assert data["status"] in ("rejected", "failed")
    assert "forwarding" not in steps
    assert "escrow" not in steps
    assert "trust_recording" not in steps
    assert "settled" not in steps


# ── 2. Provider failure = no settlement, no escrow ──────────


@pytest.mark.asyncio
async def test_provider_failure_no_settlement(client: AsyncClient):
    """When provider fails, there must be NO escrow and NO settlement.

    Invariant: Failed responses never reach escrow or settled state.
    """
    consumer = await create_agent(
        client,
        {"name": "inv-consumer", "endpoint": "http://localhost:19810", "capabilities": []},
    )

    await create_agent(
        client,
        {
            "name": "offline-provider",
            "endpoint": "http://localhost:19811",
            "capabilities": [{"name": "work", "description": "Work", "languages": ["en"], "price_per_request": 1.0}],
        },
    )

    resp = await client.post(
        "/api/protocol/request",
        json={"from_agent": consumer["id"], "query": "do work", "capability": "work"},
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # INVARIANT: failed provider → no escrow, no settlement
    assert data["status"] != "completed"
    assert "escrow" not in steps
    assert "settled" not in steps

    # Consumer balance should be untouched
    wallet_resp = await client.get(f"/api/payments/wallets/{consumer['id']}/balance")
    balance_data = wallet_resp.json()
    assert balance_data["balance"] == 100.0  # default, untouched


# ── 3. State machine prevents illegal jumps ──────────────────


def test_state_machine_blocks_routed_to_settled():
    """Direct jump from ROUTED to SETTLED is impossible.

    This is the core economic invariant: no money moves without full lifecycle.
    """
    from nexus.protocol.state_machine import (
        InvalidTransitionError,
        RequestLifecycle,
        RequestState,
    )

    lc = RequestLifecycle("inv-test-1")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)

    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.SETTLED)


def test_state_machine_blocks_received_to_settled():
    """Cannot jump from RECEIVED directly to SETTLED."""
    from nexus.protocol.state_machine import (
        InvalidTransitionError,
        RequestLifecycle,
        RequestState,
    )

    lc = RequestLifecycle("inv-test-2")
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.SETTLED)


def test_state_machine_blocks_forwarding_to_settled():
    """Cannot settle directly after forwarding — must go through trust first."""
    from nexus.protocol.state_machine import (
        InvalidTransitionError,
        RequestLifecycle,
        RequestState,
    )

    lc = RequestLifecycle("inv-test-3")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.BUDGET_CHECKED)
    lc.transition(RequestState.FORWARDING)
    lc.transition(RequestState.RESPONSE_RECEIVED)

    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.SETTLED)


# ── 4. Stale agents excluded from routing ────────────────────


@pytest.mark.asyncio
async def test_stale_agent_not_routed(client: AsyncClient):
    """Agent marked offline must not appear in routing candidates.

    Tests the last mile: reaper marks offline → router excludes.
    """
    from nexus.database import get_db

    agent = await create_agent(
        client,
        {
            "name": "stale-agent",
            "endpoint": "http://localhost:19820",
            "capabilities": [{"name": "stale_cap", "description": "Test", "languages": ["en"]}],
        },
    )

    # Manually mark agent offline (simulating reaper)
    db = await get_db()
    await db.execute("UPDATE agents SET status = 'offline' WHERE id = ?", (agent["id"],))
    await db.commit()

    # Request should fail — no online agents
    resp = await client.post(
        "/api/protocol/request",
        json={"from_agent": "consumer-1", "query": "test", "capability": "stale_cap"},
    )
    data = resp.json()
    assert data["status"] in ("failed", "rejected")
    assert "No suitable agent" in data.get("error", "")


# ── 5. Audit trail covers full lifecycle ─────────────────────


@pytest.mark.asyncio
async def test_audit_trail_complete_on_failure(client: AsyncClient):
    """Even on failure, audit trail must capture every lifecycle step that ran."""
    consumer = await create_agent(
        client,
        {"name": "audit-consumer", "endpoint": "http://localhost:19830", "capabilities": []},
    )

    await create_agent(
        client,
        {
            "name": "audit-provider",
            "endpoint": "http://localhost:19831",
            "capabilities": [
                {"name": "audit_test", "description": "Test", "languages": ["en"], "price_per_request": 0.5}
            ],
        },
    )

    resp = await client.post(
        "/api/protocol/request",
        json={"from_agent": consumer["id"], "query": "audit me", "capability": "audit_test"},
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # INVARIANT: every step that ran must be in trail with timestamps
    assert "received" in steps
    assert "policy_check" in steps
    assert "routing" in steps
    assert "budget_check" in steps
    assert "forwarding" in steps

    # Every step must have a timestamp
    for step in trail.get("steps", []):
        assert "at" in step, f"Step {step['step']} missing timestamp"
        assert isinstance(step["at"], float), f"Step {step['step']} timestamp not float"


# ── 6. Budget check is real, not decorative ──────────────────


@pytest.mark.asyncio
async def test_budget_check_prevents_dispatch_even_with_partial_funds(client: AsyncClient):
    """Consumer with 100 credits can't use agent costing 150."""
    await create_agent(
        client,
        {
            "name": "pricey-agent",
            "endpoint": "http://localhost:19840",
            "capabilities": [
                {"name": "expensive", "description": "Expensive", "languages": ["en"], "price_per_request": 150.0}
            ],
        },
    )

    # Consumer gets default 100 credits — not enough for 150
    consumer = await create_agent(
        client,
        {"name": "budget-consumer", "endpoint": "http://localhost:19841", "capabilities": []},
    )

    resp = await client.post(
        "/api/protocol/request",
        json={"from_agent": consumer["id"], "query": "too expensive", "capability": "expensive"},
    )
    data = resp.json()
    trail = data.get("meta", {}).get("trail", {})
    steps = [s["step"] for s in trail.get("steps", [])]

    # INVARIANT: forwarding must NOT happen when funds insufficient
    assert data["status"] in ("rejected", "failed")
    assert "forwarding" not in steps
    assert "insufficient_funds" in steps


# ── 7. Escrow is the only settlement path ────────────────────


@pytest.mark.asyncio
async def test_no_direct_payment_in_handler(client: AsyncClient):
    """Handler must NEVER call process_payment — only create_escrow.

    This is the core economic invariant: no settlement bypasses escrow.
    """
    import inspect

    from nexus.protocol import handler

    source = inspect.getsource(handler.handle_request)

    # Escrow must be in the handler
    assert "create_escrow" in source

    # process_payment must be GONE — no fallback, no bypass
    payment_count = source.count("process_payment")
    assert payment_count == 0, f"process_payment found {payment_count} times in handler — must be 0"


# ── 8. Escrow release and refund are mutually exclusive ──────


@pytest.mark.asyncio
async def test_escrow_double_release_blocked(client: AsyncClient):
    """Same escrow cannot be released twice.

    Invariant: Second release returns error, no double payment.
    """
    from nexus.defense.service import create_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "esc-consumer", "endpoint": "http://localhost:19850", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "esc-provider", "endpoint": "http://localhost:19851", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="inv-test-escrow-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )

    # First release — should succeed
    result1 = await release_escrow(escrow["escrow_id"])
    assert "error" not in result1
    assert result1["status"] == "released"

    # Second release — must fail
    result2 = await release_escrow(escrow["escrow_id"])
    assert "error" in result2


@pytest.mark.asyncio
async def test_escrow_release_after_dispute_blocked(client: AsyncClient):
    """Disputed escrow cannot be released.

    Invariant: Refund and Release are mutually exclusive.
    """
    from nexus.defense.service import create_escrow, dispute_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "esc2-consumer", "endpoint": "http://localhost:19852", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "esc2-provider", "endpoint": "http://localhost:19853", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="inv-test-escrow-2",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )

    # Dispute first
    dispute_result = await dispute_escrow(escrow["escrow_id"], reason="bad output")
    assert dispute_result["status"] == "disputed"

    # Release after dispute — must fail
    release_result = await release_escrow(escrow["escrow_id"])
    assert "error" in release_result


@pytest.mark.asyncio
async def test_escrow_dispute_after_release_blocked(client: AsyncClient):
    """Released escrow cannot be disputed.

    Invariant: Refund and Release are mutually exclusive (reverse direction).
    """
    from nexus.defense.service import create_escrow, dispute_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "esc3-consumer", "endpoint": "http://localhost:19854", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "esc3-provider", "endpoint": "http://localhost:19855", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="inv-test-escrow-3",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )

    # Release first
    release_result = await release_escrow(escrow["escrow_id"])
    assert release_result["status"] == "released"

    # Dispute after release — must fail
    dispute_result = await dispute_escrow(escrow["escrow_id"], reason="too late")
    assert "error" in dispute_result
