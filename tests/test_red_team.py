"""Red Team Attack Tests — prove protocol resists adversarial exploitation.

These are the 8 attack scenarios from ChatGPT's Red Team Playbook:
1. Ghost Release — parallel release+refund+challenge on same escrow
2. Late Callback Resurrection — interaction recorded after terminal state
3. Replay Within Window — identical requests fired in tight burst
4. Payload Swap — same request_id with different payload
5. Eligibility Split Brain — agent drops between routing and dispatch
6. Reconciler Double Tap — covered in test_chaos.py
7. Budget Double Spend — covered in test_chaos.py
8. Shadow Path — call deprecated/internal services directly
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


# ── 1. Ghost Release Attack ──────────────────────────────────


@pytest.mark.asyncio
async def test_ghost_release_attack(client: AsyncClient):
    """Attacker fires release + dispute + challenge simultaneously on same escrow.

    Invariant: exactly ONE economic outcome. No double-credit, no double-refund.
    The escrow ends in exactly one terminal state.
    """
    from nexus.defense.service import (
        create_challenge,
        create_escrow,
        dispute_escrow,
        release_escrow,
        resolve_challenge,
    )

    consumer = await create_agent(
        client,
        {"name": "ghost-consumer", "endpoint": "http://localhost:19900", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "ghost-provider", "endpoint": "http://localhost:19901", "capabilities": []},
    )
    attacker = await create_agent(
        client,
        {"name": "ghost-attacker", "endpoint": "http://localhost:19902", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="ghost-attack-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=20.0,
    )
    escrow_id = escrow["escrow_id"]

    # Create a challenge
    challenge = await create_challenge(
        request_id="ghost-attack-1",
        challenger_id=attacker["id"],
        target_id=provider["id"],
        reason="ghost attack",
    )

    # Fire all three concurrently: release + dispute + challenge resolve
    results = await asyncio.gather(
        release_escrow(escrow_id),
        dispute_escrow(escrow_id, reason="ghost dispute"),
        resolve_challenge(challenge["challenge_id"], upheld=True, ruling="ghost ruling"),
    )

    release_result, dispute_result, _challenge_result = results

    # Escrow: exactly ONE of release/dispute should succeed
    escrow_successes = sum(1 for r in [release_result, dispute_result] if "error" not in r)
    assert escrow_successes == 1, f"Expected exactly 1 escrow outcome, got {escrow_successes}"

    # Verify final escrow state is consistent
    from nexus.database import get_db

    db = await get_db()
    row = await db.execute("SELECT status FROM escrow WHERE escrow_id = ?", (escrow_id,))
    final = await row.fetchone()
    assert final["status"] in ("released", "disputed")

    # Verify no double payment: check provider and consumer balances are consistent
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    consumer_balance = (await row.fetchone())["balance"]
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (provider["id"],))
    provider_balance = (await row.fetchone())["balance"]

    if final["status"] == "released":
        # Consumer was debited (80), provider was credited (120)
        assert consumer_balance == 80.0, f"Consumer balance should be 80, got {consumer_balance}"
        assert provider_balance == 120.0, f"Provider balance should be 120, got {provider_balance}"
    elif final["status"] == "disputed":
        # Consumer was refunded (100), provider was NOT credited (100)
        assert consumer_balance == 100.0, f"Consumer balance should be 100, got {consumer_balance}"
        assert provider_balance == 100.0, f"Provider balance should be 100, got {provider_balance}"


# ── 2. Late Callback Resurrection Attack ─────────────────────


@pytest.mark.asyncio
async def test_late_callback_after_terminal_state(client: AsyncClient):
    """Record an interaction AFTER the escrow is already resolved.

    Invariant: late interaction recording must not create a second
    trust ledger entry for the same request_id.
    """
    from nexus.defense.service import create_escrow, release_escrow
    from nexus.trust.service import record_interaction

    consumer = await create_agent(
        client,
        {"name": "late-cb-consumer", "endpoint": "http://localhost:19903", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "late-cb-provider", "endpoint": "http://localhost:19904", "capabilities": []},
    )

    # Full lifecycle: escrow + release
    escrow = await create_escrow(
        request_id="late-callback-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )
    await release_escrow(escrow["escrow_id"])

    # Record interaction (normal part of lifecycle)
    await record_interaction(
        request_id="late-callback-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        success=True,
        confidence=0.9,
        cost=5.0,
        response_ms=100,
    )

    # ATTACK: late duplicate callback — try recording again
    await record_interaction(
        request_id="late-callback-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        success=True,
        confidence=0.9,
        cost=5.0,
        response_ms=100,
    )

    # INVARIANT: exactly 1 trust ledger entry (UNIQUE constraint)
    resp = await client.get(f"/api/trust/ledger/{provider['id']}")
    ledger = resp.json()
    matching = [e for e in ledger if e["request_id"] == "late-callback-1"]
    assert len(matching) == 1, f"Expected 1 ledger entry, got {len(matching)} — resurrection attack succeeded"


# ── 3. Replay Within Window Attack ──────────────────────────


@pytest.mark.asyncio
async def test_replay_within_window_attack(client: AsyncClient):
    """Fire 50 identical requests with same request_id simultaneously.

    Invariant: at most 1 processes, rest are rejected as duplicates.
    No double escrow, no double trust delta.
    """
    payload = {
        "request_id": "replay-attack-fixed-id",
        "from_agent": "replay-attacker",
        "query": "replay attack",
        "capability": "nonexistent",
    }

    tasks = [client.post("/api/protocol/request", json=payload) for _ in range(50)]
    await asyncio.gather(*tasks)

    # INVARIANT: at most 1 non-duplicate response
    # (May be 0 if the first also fails for other reasons like no capability)
    from nexus.database import get_db

    db = await get_db()

    # No double escrow
    row = await db.execute(
        "SELECT COUNT(*) as c FROM escrow WHERE request_id = 'replay-attack-fixed-id'"
    )
    assert (await row.fetchone())["c"] <= 1

    # No double trust ledger
    row = await db.execute(
        "SELECT COUNT(*) as c FROM trust_ledger WHERE request_id = 'replay-attack-fixed-id'"
    )
    assert (await row.fetchone())["c"] <= 1


# ── 4. Payload Swap Attack ──────────────────────────────────


@pytest.mark.asyncio
async def test_payload_swap_attack(client: AsyncClient):
    """Send request with same request_id but different payload/query.

    Invariant: second request rejected regardless of payload difference.
    The request_id is the idempotency key, not the content.
    """
    # First request
    payload1 = {
        "request_id": "payload-swap-id",
        "from_agent": "swap-attacker",
        "query": "legitimate query",
        "capability": "nonexistent",
    }
    await client.post("/api/protocol/request", json=payload1)

    # Second request — SAME request_id, DIFFERENT payload
    payload2 = {
        "request_id": "payload-swap-id",
        "from_agent": "swap-attacker",
        "query": "MALICIOUS REPLACEMENT QUERY",
        "capability": "different_capability",
    }
    resp2 = await client.post("/api/protocol/request", json=payload2)

    # INVARIANT: second request must be rejected as duplicate
    data2 = resp2.json()
    assert data2["status"] == "rejected"
    assert "Duplicate" in data2.get("error", "")


# ── 5. Eligibility Split Brain Attack ────────────────────────


@pytest.mark.asyncio
async def test_eligibility_split_brain_concurrent_requests(client: AsyncClient):
    """Agent goes offline while multiple requests target it concurrently.

    Invariant: all requests that reach dispatch after agent goes offline
    must fail. No forwarding to offline agents.
    """
    from nexus.database import get_db

    consumer = await create_agent(
        client,
        {"name": "split-consumer", "endpoint": "http://localhost:19905", "capabilities": []},
    )
    agent = await create_agent(
        client,
        {
            "name": "split-agent",
            "endpoint": "http://localhost:19906",
            "capabilities": [{"name": "split_test", "description": "Test", "languages": ["en"]}],
        },
    )

    # Take agent offline
    db = await get_db()
    await db.execute("UPDATE agents SET status = 'offline' WHERE id = ?", (agent["id"],))
    await db.commit()

    # Fire concurrent requests
    tasks = [
        client.post(
            "/api/protocol/request",
            json={
                "request_id": f"split-brain-{i}",
                "from_agent": consumer["id"],
                "query": "test",
                "capability": "split_test",
            },
        )
        for i in range(20)
    ]
    responses = await asyncio.gather(*tasks)

    # INVARIANT: ALL must fail
    for resp in responses:
        data = resp.json()
        assert data["status"] in ("failed", "rejected"), f"Request succeeded with offline agent: {data}"

    # No escrow created
    row = await db.execute(
        "SELECT COUNT(*) as c FROM escrow WHERE provider_id = ?", (agent["id"],)
    )
    assert (await row.fetchone())["c"] == 0


# ── 6. Shadow Path Attack (deprecated API bypass) ────────────


@pytest.mark.asyncio
async def test_shadow_path_direct_payment_deprecation(client: AsyncClient):
    """Attacker tries to use deprecated process_payment() to bypass escrow.

    Invariant: process_payment emits DeprecationWarning. Handler never uses it.
    The settlement path is escrow-only.
    """
    import inspect
    import warnings

    from nexus.payments.service import process_payment
    from nexus.protocol import handler

    # 1. Verify handler source has no process_payment calls
    source = inspect.getsource(handler.handle_request)
    assert "process_payment" not in source, "process_payment found in handler — shadow path exists!"

    # 2. Verify process_payment warns when called directly
    consumer = await create_agent(
        client,
        {"name": "shadow-consumer", "endpoint": "http://localhost:19907", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "shadow-provider", "endpoint": "http://localhost:19908", "capabilities": []},
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await process_payment(
            request_id="shadow-path-1",
            consumer_id=consumer["id"],
            provider_id=provider["id"],
            amount=1.0,
        )
        assert len(w) >= 1
        assert issubclass(w[0].category, DeprecationWarning)


# ── 7. Escrow Amount Manipulation Attack ─────────────────────


@pytest.mark.asyncio
async def test_escrow_cannot_be_released_for_different_amount(client: AsyncClient):
    """Verify escrow release credits exactly the escrowed amount.

    Invariant: provider gets exactly what was escrowed, not more.
    """
    from nexus.defense.service import create_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "amt-consumer", "endpoint": "http://localhost:19909", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "amt-provider", "endpoint": "http://localhost:19910", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="amt-attack-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )

    # Release
    result = await release_escrow(escrow["escrow_id"])
    assert result["amount"] == 5.0

    # Verify exact balances
    from nexus.database import get_db

    db = await get_db()

    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (provider["id"],))
    provider_balance = (await row.fetchone())["balance"]
    # Provider started with 100, gets +5 from escrow release
    assert provider_balance == 105.0, f"Provider should have 105, got {provider_balance}"

    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    consumer_balance = (await row.fetchone())["balance"]
    # Consumer started with 100, debited 5 at escrow creation
    assert consumer_balance == 95.0, f"Consumer should have 95, got {consumer_balance}"


# ── 8. Trust Farming via Rapid Self-Interaction ──────────────


@pytest.mark.asyncio
async def test_trust_farming_bounded_by_ledger(client: AsyncClient):
    """Agent tries to farm trust by recording many interactions rapidly.

    Invariant: trust is bounded by MAX_TRUST. Each interaction creates
    exactly one ledger entry. UNIQUE constraint prevents replay.
    """
    from nexus.config import MAX_TRUST
    from nexus.trust.service import record_interaction

    agent = await create_agent(
        client,
        {"name": "trust-farmer", "endpoint": "http://localhost:19911", "capabilities": []},
    )
    agent_id = agent["id"]

    # Record 100 successful interactions
    for i in range(100):
        await record_interaction(
            request_id=f"farm-{i}",
            consumer_id=f"farmer-consumer-{i}",
            provider_id=agent_id,
            success=True,
            confidence=0.95,
            cost=0.1,
            response_ms=50,
        )

    # INVARIANT: trust cannot exceed MAX_TRUST
    resp = await client.get(f"/api/trust/report/{agent_id}")
    report = resp.json()
    assert report["trust_score"] <= MAX_TRUST, f"Trust exceeds MAX: {report['trust_score']}"

    # INVARIANT: exactly 100 ledger entries (no duplicates)
    ledger_resp = await client.get(f"/api/trust/ledger/{agent_id}?limit=200")
    ledger = ledger_resp.json()
    assert len(ledger) == 100

    # Try replaying — same request_ids should be ignored
    for i in range(10):
        await record_interaction(
            request_id=f"farm-{i}",  # duplicate!
            consumer_id=f"farmer-consumer-{i}",
            provider_id=agent_id,
            success=True,
            confidence=0.95,
            cost=0.1,
            response_ms=50,
        )

    # INVARIANT: still exactly 100 entries (replays ignored)
    ledger_resp2 = await client.get(f"/api/trust/ledger/{agent_id}?limit=200")
    ledger2 = ledger_resp2.json()
    assert len(ledger2) == 100, f"Expected 100, got {len(ledger2)} — replay attack succeeded"
