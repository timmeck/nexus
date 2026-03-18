"""Crash-Injection Tests — simulate process kill at critical lifecycle edges.

These tests verify that the system recovers correctly when operations
are interrupted between CAS and follow-up actions. Since we can't actually
kill the process in a test, we simulate partial completion by:
1. Performing the CAS (UPDATE WHERE status='held') manually
2. NOT performing the follow-up (credit/debit/transaction)
3. Running reconciliation to verify it heals correctly

The 7 critical edges from the Crash Table:
1. After escrow CREATE, before event persistence
2. After CAS release, before provider credit
3. After CAS dispute, before consumer refund
4. After trust recording, before escrow creation
5. After challenge resolution, before slash
6. During reconciliation, between detect and repair
7. After forwarding, before response processing
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


# ── Edge 1: Crash after escrow CREATE, orphaned held escrow ───


@pytest.mark.asyncio
async def test_crash_after_escrow_create_reconciler_heals(client: AsyncClient):
    """Escrow created but request never reaches SETTLED (process died).

    Invariant: reconciler detects orphaned escrow and refunds consumer.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "crash1-consumer", "endpoint": "http://localhost:19920", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "crash1-provider", "endpoint": "http://localhost:19921", "capabilities": []},
    )

    # Simulate: escrow created, then process dies
    await create_escrow(
        request_id="crash-edge-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=10.0,
    )

    # Simulate terminal event (as if handler failed after escrow)
    db = await get_db()
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-crash1", "crash-edge-1", "error", "", "error", "system", "{}", datetime.utcnow().isoformat()),
    )
    await db.commit()

    # Consumer balance should be debited (90)
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 90.0

    # Reconciler should detect and refund
    result = await reconcile_once()
    assert result["orphaned_escrows_refunded"] == 1

    # Consumer balance restored
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 100.0


# ── Edge 2: Crash after CAS release, before provider credit ──


@pytest.mark.asyncio
async def test_crash_after_cas_release_partial_state(client: AsyncClient):
    """CAS marks escrow 'released' but process dies before crediting provider.

    This simulates the worst-case partial completion. We verify the escrow
    status is 'released' (CAS succeeded) and that a second release fails
    (no double-credit possible even if first credit was lost).
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, release_escrow

    consumer = await create_agent(
        client,
        {"name": "crash2-consumer", "endpoint": "http://localhost:19922", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "crash2-provider", "endpoint": "http://localhost:19923", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="crash-edge-2",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=10.0,
    )

    # Simulate partial: do CAS manually without credit
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "UPDATE escrow SET status = 'released', resolved_at = ? WHERE escrow_id = ? AND status = 'held'",
        (now, escrow["escrow_id"]),
    )
    assert cursor.rowcount == 1  # CAS succeeded
    await db.commit()

    # Provider was NOT credited (simulating crash)
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (provider["id"],))
    provider_balance = (await row.fetchone())["balance"]
    assert provider_balance == 100.0  # unchanged — credit was lost

    # INVARIANT: second release attempt fails (CAS prevents double-credit)
    result = await release_escrow(escrow["escrow_id"])
    assert "error" in result

    # Escrow is in terminal state — reconciler won't touch it
    row = await db.execute("SELECT status FROM escrow WHERE escrow_id = ?", (escrow["escrow_id"],))
    assert (await row.fetchone())["status"] == "released"


# ── Edge 3: Crash after CAS dispute, before consumer refund ──


@pytest.mark.asyncio
async def test_crash_after_cas_dispute_partial_state(client: AsyncClient):
    """CAS marks escrow 'disputed' but process dies before refunding consumer.

    Same pattern as Edge 2 but for disputes. Verifies CAS prevents
    double-dispute even when refund was lost.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, dispute_escrow

    consumer = await create_agent(
        client,
        {"name": "crash3-consumer", "endpoint": "http://localhost:19924", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "crash3-provider", "endpoint": "http://localhost:19925", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="crash-edge-3",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=10.0,
    )

    # Simulate partial: do CAS manually without refund
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "UPDATE escrow SET status = 'disputed', resolved_at = ? WHERE escrow_id = ? AND status = 'held'",
        (now, escrow["escrow_id"]),
    )
    assert cursor.rowcount == 1
    await db.commit()

    # Consumer was NOT refunded (simulating crash)
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    consumer_balance = (await row.fetchone())["balance"]
    assert consumer_balance == 90.0  # still debited — refund was lost

    # INVARIANT: second dispute attempt fails
    result = await dispute_escrow(escrow["escrow_id"], reason="retry after crash")
    assert "error" in result

    # No double-dispute possible
    row = await db.execute(
        "SELECT COUNT(*) as c FROM escrow WHERE escrow_id = ? AND status = 'disputed'",
        (escrow["escrow_id"],),
    )
    assert (await row.fetchone())["c"] == 1


# ── Edge 4: Crash after trust recording, before escrow creation ──


@pytest.mark.asyncio
async def test_crash_after_trust_before_escrow(client: AsyncClient):
    """Trust was recorded but escrow was never created (process died).

    Invariant: trust ledger has the entry. No escrow exists.
    This is a "lost payment" scenario — the work was done but never settled.
    The system should be queryable to detect this mismatch.
    """
    from nexus.database import get_db
    from nexus.trust.service import record_interaction

    consumer = await create_agent(
        client,
        {"name": "crash4-consumer", "endpoint": "http://localhost:19926", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "crash4-provider", "endpoint": "http://localhost:19927", "capabilities": []},
    )

    # Trust recorded
    await record_interaction(
        request_id="crash-edge-4",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        success=True,
        confidence=0.9,
        cost=5.0,
        response_ms=100,
    )

    # Escrow NOT created (simulating crash)

    # INVARIANT: trust ledger has the entry
    resp = await client.get(f"/api/trust/ledger/{provider['id']}")
    ledger = resp.json()
    matching = [e for e in ledger if e["request_id"] == "crash-edge-4"]
    assert len(matching) == 1

    # INVARIANT: no escrow exists for this request
    db = await get_db()
    row = await db.execute("SELECT COUNT(*) as c FROM escrow WHERE request_id = 'crash-edge-4'")
    assert (await row.fetchone())["c"] == 0

    # Cross-object consistency check: trust exists without escrow
    # This is a detectable mismatch that a future integrity monitor could flag
    row = await db.execute(
        """SELECT tl.request_id
           FROM trust_ledger tl
           LEFT JOIN escrow e ON tl.request_id = e.request_id
           WHERE tl.request_id = 'crash-edge-4' AND e.escrow_id IS NULL""",
    )
    orphan = await row.fetchone()
    assert orphan is not None, "Cross-object mismatch not detectable"


# ── Edge 5: Crash after challenge resolution, before slash ───


@pytest.mark.asyncio
async def test_crash_after_challenge_resolve_before_slash(client: AsyncClient):
    """Challenge resolved (CAS) but slash never executed (process died).

    Invariant: challenge is in terminal state. Second resolve fails.
    Agent trust unchanged (slash was lost).
    """
    from nexus.database import get_db
    from nexus.defense.service import create_challenge, resolve_challenge

    challenger = await create_agent(
        client,
        {"name": "crash5-challenger", "endpoint": "http://localhost:19928", "capabilities": []},
    )
    target = await create_agent(
        client,
        {"name": "crash5-target", "endpoint": "http://localhost:19929", "capabilities": []},
    )

    challenge = await create_challenge(
        request_id="crash-edge-5",
        challenger_id=challenger["id"],
        target_id=target["id"],
        reason="crash test",
    )

    # Simulate partial: CAS on challenge only, skip slash
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "UPDATE challenges SET status = 'upheld', ruling = 'crash test', resolved_at = ? WHERE challenge_id = ? AND status = 'pending'",
        (now, challenge["challenge_id"]),
    )
    assert cursor.rowcount == 1
    await db.commit()

    # Target trust unchanged (slash was lost)
    row = await db.execute("SELECT trust_score FROM agents WHERE id = ?", (target["id"],))
    trust = (await row.fetchone())["trust_score"]
    assert trust == 0.5  # default, unchanged

    # INVARIANT: second resolve attempt fails
    result = await resolve_challenge(challenge["challenge_id"], upheld=True, ruling="retry")
    assert "error" in result


# ── Edge 6: Crash during reconciliation between detect and repair ──


@pytest.mark.asyncio
async def test_crash_during_reconciliation_idempotent_retry(client: AsyncClient):
    """Reconciler detects orphan, starts repair, crashes, retries.

    Invariant: second reconciliation pass is idempotent — no double refund.
    """
    from nexus.database import get_db
    from nexus.defense.service import create_escrow, dispute_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "crash6-consumer", "endpoint": "http://localhost:19930", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "crash6-provider", "endpoint": "http://localhost:19931", "capabilities": []},
    )

    # Create orphaned escrow
    escrow = await create_escrow(
        request_id="crash-edge-6",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=10.0,
    )

    db = await get_db()
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-crash6", "crash-edge-6", "provider_failed", "", "provider_failed", "system", "{}", datetime.utcnow().isoformat()),
    )
    await db.commit()

    # Simulate partial reconciliation: dispute manually (as if reconciler did it)
    await dispute_escrow(escrow["escrow_id"], reason="partial reconciliation")

    # Now run full reconciliation — should find nothing (escrow already disputed)
    result = await reconcile_once()
    assert result["orphaned_escrows_refunded"] == 0

    # Consumer balance: was debited 10, refunded 10 = 100
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 100.0

    # Escrow in terminal state
    row = await db.execute("SELECT status FROM escrow WHERE escrow_id = ?", (escrow["escrow_id"],))
    assert (await row.fetchone())["status"] == "disputed"


# ── Edge 7: Crash after forwarding, before response processing ──


@pytest.mark.asyncio
async def test_crash_after_forwarding_no_orphaned_escrow(client: AsyncClient):
    """Request forwarded to agent, process dies before response handling.

    Invariant: no escrow was created (response never came back).
    No economic side effects from a request that never completed.
    """
    from nexus.database import get_db

    consumer = await create_agent(
        client,
        {"name": "crash7-consumer", "endpoint": "http://localhost:19932", "capabilities": []},
    )
    # Agent at unreachable endpoint — simulates "forwarded then crashed"
    await create_agent(
        client,
        {
            "name": "crash7-provider",
            "endpoint": "http://localhost:19933",
            "capabilities": [
                {"name": "crash_test", "description": "Test", "languages": ["en"], "price_per_request": 5.0}
            ],
        },
    )

    # Send request — will fail at forwarding (agent unreachable)
    resp = await client.post(
        "/api/protocol/request",
        json={
            "request_id": "crash-edge-7",
            "from_agent": consumer["id"],
            "query": "crash test",
            "capability": "crash_test",
        },
    )
    data = resp.json()

    # Request should fail
    assert data["status"] != "completed"

    # INVARIANT: no escrow created for failed forwarding
    db = await get_db()
    row = await db.execute("SELECT COUNT(*) as c FROM escrow WHERE request_id = 'crash-edge-7'")
    assert (await row.fetchone())["c"] == 0

    # INVARIANT: consumer balance untouched
    row = await db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (consumer["id"],))
    assert (await row.fetchone())["balance"] == 100.0
