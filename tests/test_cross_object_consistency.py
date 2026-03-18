"""Cross-Object Consistency Tests — detect and verify illegal state combinations.

These tests build deliberately illegal state combinations between
domain objects (Request, Escrow, Trust, Challenge) and verify that:
1. The system can detect them via SQL queries
2. Reconciliation repairs what it can
3. CAS prevents creating new illegal states
4. Invariant: released_amount == reserved_amount == agreed_price

Maps to Fehlerklasse #3 (Split-Brain) from the consistency matrix.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


# ── 1. Escrow exists without matching request event ──────────


@pytest.mark.asyncio
async def test_escrow_without_request_event_detectable(client: AsyncClient):
    """Escrow created but no request_events exist for that request_id.

    This is an illegal state: escrow should only exist for requests
    that went through the handler. Detectable via LEFT JOIN.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow

    consumer = await create_agent(
        client,
        {"name": "cross1-consumer", "endpoint": "http://localhost:19940", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "cross1-provider", "endpoint": "http://localhost:19941", "capabilities": []},
    )

    # Create escrow directly (bypassing handler — simulating inconsistency)
    await create_escrow(
        request_id="orphan-escrow-no-event",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )

    # Detection query: find escrows without request events
    db = await get_db()
    row = await db.execute(
        """SELECT e.escrow_id, e.request_id
           FROM escrow e
           LEFT JOIN request_events re ON e.request_id = re.request_id
           WHERE re.event_id IS NULL"""
    )
    orphans = await row.fetchall()

    # INVARIANT: the orphan is detectable
    assert len(orphans) >= 1
    orphan_ids = [o["request_id"] for o in orphans]
    assert "orphan-escrow-no-event" in orphan_ids


# ── 2. Trust ledger entry without matching interaction ────────


@pytest.mark.asyncio
async def test_trust_ledger_without_interaction_detectable(client: AsyncClient):
    """Trust ledger has entry but interactions table doesn't.

    This shouldn't happen under normal operation. Detectable via LEFT JOIN.
    """
    from nexus.database import get_db

    agent = await create_agent(
        client,
        {"name": "cross2-agent", "endpoint": "http://localhost:19942", "capabilities": []},
    )

    # Insert trust ledger entry directly (bypassing record_interaction)
    db = await get_db()
    await db.execute(
        """INSERT INTO trust_ledger
           (entry_id, agent_id, request_id, delta, reason, trust_before, trust_after, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("orphan-ledger-1", agent["id"], "ghost-request-999", 0.1, "success", 0.5, 0.6, datetime.utcnow().isoformat()),
    )
    await db.commit()

    # Detection query
    row = await db.execute(
        """SELECT tl.entry_id, tl.request_id
           FROM trust_ledger tl
           LEFT JOIN interactions i ON tl.request_id = i.request_id AND tl.agent_id = i.provider_id
           WHERE i.interaction_id IS NULL"""
    )
    orphans = await row.fetchall()

    assert len(orphans) >= 1
    orphan_ids = [o["request_id"] for o in orphans]
    assert "ghost-request-999" in orphan_ids


# ── 3. Held escrow + terminal request event (reconcilable) ───


@pytest.mark.asyncio
async def test_held_escrow_with_terminal_event_reconciled(client: AsyncClient):
    """Held escrow for a request that has a terminal event.

    This is a known reconcilable state. Reconciler should refund it.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "cross3-consumer", "endpoint": "http://localhost:19943", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "cross3-provider", "endpoint": "http://localhost:19944", "capabilities": []},
    )

    await create_escrow(
        request_id="cross-recon-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=8.0,
    )

    # Add terminal event
    db = await get_db()
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-cross3", "cross-recon-1", "error", "", "error", "system", "{}", datetime.utcnow().isoformat()),
    )
    await db.commit()

    # Before reconciliation
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 92.0  # debited

    # Reconcile
    result = await reconcile_once()
    assert result["orphaned_escrows_refunded"] == 1

    # After reconciliation — balance restored
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 100.0


# ── 4. Released escrow amount matches creation amount ─────────


@pytest.mark.asyncio
async def test_released_amount_equals_reserved_amount(client: AsyncClient):
    """Invariant: released_amount == reserved_amount.

    No amount drift between escrow creation and release.
    This is the core economic consistency invariant.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "cross4-consumer", "endpoint": "http://localhost:19945", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "cross4-provider", "endpoint": "http://localhost:19946", "capabilities": []},
    )

    # Create escrow for specific amount
    escrow = await create_escrow(
        request_id="amount-consistency-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=7.77,
    )

    # Release
    result = await release_escrow(escrow["escrow_id"])
    assert "error" not in result

    # INVARIANT: released amount matches reserved amount
    db = await get_db()
    row = await db.execute("SELECT amount FROM escrow WHERE escrow_id = ?", (escrow["escrow_id"],))
    stored_amount = (await row.fetchone())["amount"]
    assert stored_amount == 7.77

    # INVARIANT: consumer debit + provider credit = 0 net (conservation)
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    consumer_balance = (await row.fetchone())["balance"]
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (provider["id"],))
    provider_balance = (await row.fetchone())["balance"]

    # Consumer: 100 - 7.77 = 92.23, Provider: 100 + 7.77 = 107.77
    assert abs(consumer_balance - 92.23) < 0.01
    assert abs(provider_balance - 107.77) < 0.01

    # Total money in system is conserved
    assert abs((consumer_balance + provider_balance) - 200.0) < 0.01


# ── 5. Disputed escrow: consumer refund matches original amount ──


@pytest.mark.asyncio
async def test_disputed_amount_equals_reserved_amount(client: AsyncClient):
    """Invariant: disputed refund == reserved amount.

    Consumer gets back exactly what was escrowed.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, dispute_escrow

    consumer = await create_agent(
        client,
        {"name": "cross5-consumer", "endpoint": "http://localhost:19947", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "cross5-provider", "endpoint": "http://localhost:19948", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="dispute-consistency-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=12.50,
    )

    result = await dispute_escrow(escrow["escrow_id"], reason="test")
    assert result["refunded"] == 12.50

    # Consumer fully restored
    db = await get_db()
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 100.0

    # Provider NOT credited (dispute = refund)
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (provider["id"],))
    assert (await row.fetchone())["balance"] == 100.0


# ── 6. Multiple escrows for same request_id blocked ──────────


@pytest.mark.asyncio
async def test_no_double_escrow_for_same_request(client: AsyncClient):
    """Cannot create two held escrows for the same request_id.

    The UNIQUE partial index on escrow(request_id) WHERE status='held'
    prevents this.
    """
    from nexus.defense.service import create_escrow

    consumer = await create_agent(
        client,
        {"name": "cross6-consumer", "endpoint": "http://localhost:19949", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "cross6-provider", "endpoint": "http://localhost:19950", "capabilities": []},
    )

    # First escrow succeeds
    escrow1 = await create_escrow(
        request_id="double-escrow-test",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=5.0,
    )
    assert "escrow_id" in escrow1

    # Second escrow for same request_id should fail (UNIQUE index)
    import aiosqlite

    with pytest.raises(aiosqlite.IntegrityError):
        await create_escrow(
            request_id="double-escrow-test",
            consumer_id=consumer["id"],
            provider_id=provider["id"],
            amount=5.0,
        )


# ── 7. Agent trust score matches ledger sum ──────────────────


@pytest.mark.asyncio
async def test_agent_trust_consistent_with_ledger(client: AsyncClient):
    """Agent's trust_score should reflect the cumulative ledger deltas.

    Invariant: trust_score ≈ initial_trust + sum(ledger_deltas),
    clamped to [MIN_TRUST, MAX_TRUST].
    """
    from nexus.config import MAX_TRUST, MIN_TRUST
    from nexus.database import get_db
    from nexus.trust.service import record_interaction

    agent = await create_agent(
        client,
        {"name": "cross7-agent", "endpoint": "http://localhost:19951", "capabilities": []},
    )
    agent_id = agent["id"]
    initial_trust = 0.5

    # Record mix of successes and failures
    interactions = [
        ("req-a", True, 0.9, False),
        ("req-b", True, 0.8, False),
        ("req-c", False, 0.3, False),
        ("req-d", True, 0.95, True),  # verified
        ("req-e", False, 0.2, False),
    ]

    for req_id, success, confidence, verified in interactions:
        await record_interaction(
            request_id=req_id,
            consumer_id=f"consumer-{req_id}",
            provider_id=agent_id,
            success=success,
            confidence=confidence,
            verified=verified,
            cost=1.0,
            response_ms=100,
        )

    # Get actual trust score
    db = await get_db()
    row = await db.execute("SELECT trust_score FROM agents WHERE id = ?", (agent_id,))
    actual_trust = (await row.fetchone())["trust_score"]

    # Get ledger sum
    row = await db.execute(
        "SELECT COALESCE(SUM(delta), 0) as total_delta FROM trust_ledger WHERE agent_id = ?",
        (agent_id,),
    )
    total_delta = (await row.fetchone())["total_delta"]

    # Expected trust = initial + deltas, clamped
    expected_trust = max(MIN_TRUST, min(MAX_TRUST, initial_trust + total_delta))

    # INVARIANT: actual matches expected (within floating point tolerance)
    assert abs(actual_trust - expected_trust) < 0.001, (
        f"Trust drift: actual={actual_trust}, expected={expected_trust}, delta_sum={total_delta}"
    )


# ── 8. Wallet balance conservation across full lifecycle ──────


@pytest.mark.asyncio
async def test_wallet_balance_conservation(client: AsyncClient):
    """Total money in the system is conserved across escrow lifecycle.

    Invariant: sum(all_balances) remains constant regardless of
    escrow creation, release, or dispute.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, dispute_escrow, release_escrow

    agents = []
    for i in range(4):
        agent = await create_agent(
            client,
            {"name": f"conservation-{i}", "endpoint": f"http://localhost:{19952 + i}", "capabilities": []},
        )
        agents.append(agent)

    db = await get_db()

    async def system_total():
        """Total money = wallet balances + held escrow amounts."""
        row = await db.execute("SELECT COALESCE(SUM(balance), 0) as total FROM wallets")
        wallets = (await row.fetchone())["total"]
        row = await db.execute("SELECT COALESCE(SUM(amount), 0) as total FROM escrow WHERE status = 'held'")
        held = (await row.fetchone())["total"]
        return wallets + held

    initial_total = await system_total()

    # Escrow 1: agents[0] → agents[1], 15 credits
    # Money moves from wallet to escrow — system total unchanged
    e1 = await create_escrow("conserv-1", agents[0]["id"], agents[1]["id"], 15.0)
    assert abs(await system_total() - initial_total) < 0.01

    # Release escrow 1 — money moves from escrow to provider wallet
    await release_escrow(e1["escrow_id"])
    assert abs(await system_total() - initial_total) < 0.01

    # Escrow 2: agents[2] → agents[3], 25 credits
    e2 = await create_escrow("conserv-2", agents[2]["id"], agents[3]["id"], 25.0)
    assert abs(await system_total() - initial_total) < 0.01

    # Dispute escrow 2 — money returns from escrow to consumer
    await dispute_escrow(e2["escrow_id"], reason="test")

    # After dispute: refund restores consumer, slashing may debit provider
    final_total = await system_total()
    row = await db.execute("SELECT COALESCE(SUM(credits_lost), 0) as lost FROM slashing_log")
    slashed = (await row.fetchone())["lost"]

    # INVARIANT: system_total = initial - slashed (slashing destroys credits)
    assert abs(final_total - (initial_total - slashed)) < 0.01, (
        f"Balance leak: initial={initial_total}, final={final_total}, slashed={slashed}"
    )


# ── 9. Shadow Path CI guard: no forbidden patterns in codebase ──


def test_no_forbidden_patterns_in_handler():
    """Handler must not contain direct DB writes to escrow/trust tables.

    All mutations go through defense.service and trust.service.
    Shadow paths are blocked at the source level.
    """
    import inspect

    from nexus.protocol import handler

    source = inspect.getsource(handler)

    # These patterns should NEVER appear in handler.py
    forbidden = [
        "INSERT INTO escrow",
        "UPDATE escrow",
        "INSERT INTO trust_ledger",
        "UPDATE trust_ledger",
        "INSERT INTO challenges",
        "UPDATE challenges",
        "INSERT INTO slashing_log",
        "UPDATE wallets",
    ]

    for pattern in forbidden:
        assert pattern not in source, f"Forbidden pattern '{pattern}' found in handler — shadow path risk"


def test_no_forbidden_patterns_in_router():
    """Router must not modify trust, escrow, or payment state."""
    import inspect

    from nexus.router import service as router

    source = inspect.getsource(router)

    forbidden = [
        "INSERT INTO escrow",
        "UPDATE escrow",
        "UPDATE wallets",
        "INSERT INTO trust_ledger",
        "UPDATE agents SET trust_score",
    ]

    for pattern in forbidden:
        assert pattern not in source, f"Forbidden pattern '{pattern}' found in router — shadow path risk"
