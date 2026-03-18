"""Tests for the Reconciliation job — classification, idempotent repair, audit trail."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reconcile_finds_no_issues_on_clean_system(client: AsyncClient):
    """Clean system should report zero issues."""
    from nexus.protocol.reconciliation import reconcile_once

    results = await reconcile_once()
    assert results["stuck_requests_found"] == 0
    assert results["mature_escrows_released"] == 0
    assert results["orphaned_escrows_refunded"] == 0
    assert results["repairs"] == []


@pytest.mark.asyncio
async def test_reconcile_detects_stuck_request(client: AsyncClient):
    """Request with old events and no terminal state should be classified as stuck."""
    from nexus.database import get_db
    from nexus.protocol.reconciliation import reconcile_once

    db = await get_db()
    old_time = (datetime.utcnow() - timedelta(seconds=600)).isoformat()

    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-stuck-1", "stuck-req-1", "received", "", "received", "system", "{}", old_time),
    )
    await db.commit()

    results = await reconcile_once()
    assert results["stuck_requests_found"] >= 1

    # Should have a repair entry with class and action
    stuck_repairs = [r for r in results["repairs"] if r["class"] == "stuck_request"]
    assert len(stuck_repairs) >= 1
    assert stuck_repairs[0]["action"] == "alert_only"


@pytest.mark.asyncio
async def test_reconcile_ignores_completed_requests(client: AsyncClient):
    """Request with terminal event should NOT be flagged as stuck."""
    from nexus.database import get_db
    from nexus.protocol.reconciliation import reconcile_once

    db = await get_db()
    old_time = (datetime.utcnow() - timedelta(seconds=600)).isoformat()

    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-ok-1", "ok-req-1", "received", "", "received", "system", "{}", old_time),
    )
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-ok-2", "ok-req-1", "settled", "escrow", "settled", "system", "{}", old_time),
    )
    await db.commit()

    results = await reconcile_once()
    assert results["stuck_requests_found"] == 0


@pytest.mark.asyncio
async def test_reconcile_releases_mature_escrows(client: AsyncClient):
    """Escrows past settlement window should be auto-released."""
    from nexus.database import get_db
    from nexus.defense.service import create_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "recon-consumer", "endpoint": "http://localhost:19900", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "recon-provider", "endpoint": "http://localhost:19901", "capabilities": []},
    )

    escrow = await create_escrow(
        request_id="recon-test-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=2.0,
    )

    db = await get_db()
    past = (datetime.utcnow() - timedelta(seconds=120)).isoformat()
    await db.execute(
        "UPDATE escrow SET release_at = ? WHERE escrow_id = ?",
        (past, escrow["escrow_id"]),
    )
    await db.commit()

    results = await reconcile_once()
    assert results["mature_escrows_released"] >= 1

    # Should have repair entry
    mature_repairs = [r for r in results["repairs"] if r["class"] == "mature_escrow"]
    assert len(mature_repairs) >= 1


@pytest.mark.asyncio
async def test_reconcile_refunds_orphaned_escrow(client: AsyncClient):
    """Held escrow for a failed request should be auto-refunded."""
    from nexus.database import get_db
    from nexus.defense.service import create_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "orphan-consumer", "endpoint": "http://localhost:19910", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "orphan-provider", "endpoint": "http://localhost:19911", "capabilities": []},
    )

    # Create escrow
    await create_escrow(
        request_id="orphan-req-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=3.0,
    )

    # Simulate failed request terminal event
    db = await get_db()
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "ev-orphan-1",
            "orphan-req-1",
            "provider_failed",
            "forwarding",
            "provider_failed",
            "system",
            "{}",
            datetime.utcnow().isoformat(),
        ),
    )
    await db.commit()

    results = await reconcile_once()
    assert results["orphaned_escrows_refunded"] >= 1

    # Escrow should now be disputed (refunded)
    row = await db.execute("SELECT status FROM escrow WHERE request_id = 'orphan-req-1'")
    esc = await row.fetchone()
    assert esc["status"] == "disputed"


@pytest.mark.asyncio
async def test_reconcile_idempotent_double_run(client: AsyncClient):
    """Running reconciliation twice must not cause double effects."""
    from nexus.database import get_db
    from nexus.defense.service import create_escrow
    from nexus.protocol.reconciliation import reconcile_once

    consumer = await create_agent(
        client,
        {"name": "idemp-consumer", "endpoint": "http://localhost:19920", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "idemp-provider", "endpoint": "http://localhost:19921", "capabilities": []},
    )

    await create_escrow(
        request_id="idemp-req-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=2.0,
    )

    # Simulate failed request
    db = await get_db()
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-idemp-1", "idemp-req-1", "error", "", "error", "system", "{}", datetime.utcnow().isoformat()),
    )
    await db.commit()

    # First run
    r1 = await reconcile_once()
    assert r1["orphaned_escrows_refunded"] >= 1

    # Second run — must NOT refund again
    r2 = await reconcile_once()
    assert r2["orphaned_escrows_refunded"] == 0


@pytest.mark.asyncio
async def test_reconcile_writes_audit_trail(client: AsyncClient):
    """Reconciliation actions must produce audit events."""
    from nexus.database import get_db
    from nexus.protocol.reconciliation import reconcile_once

    db = await get_db()
    old_time = (datetime.utcnow() - timedelta(seconds=600)).isoformat()

    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-audit-recon", "audit-recon-req", "routing", "", "routing", "system", "{}", old_time),
    )
    await db.commit()

    await reconcile_once()

    # Check that reconciler wrote its own events
    rows = await db.execute("SELECT * FROM request_events WHERE actor = 'reconciler'")
    recon_events = await rows.fetchall()
    assert len(recon_events) >= 1

    # Event should contain classification details
    import json

    details = json.loads(recon_events[0]["details"])
    assert "class" in details
    assert "action" in details


@pytest.mark.asyncio
async def test_unique_escrow_per_request(client: AsyncClient):
    """Only one held escrow per request_id — DB constraint enforced."""
    import sqlite3

    from nexus.defense.service import create_escrow

    consumer = await create_agent(
        client,
        {"name": "unique-consumer", "endpoint": "http://localhost:19902", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "unique-provider", "endpoint": "http://localhost:19903", "capabilities": []},
    )

    await create_escrow(
        request_id="unique-escrow-test",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=1.0,
    )

    with pytest.raises(sqlite3.IntegrityError):
        await create_escrow(
            request_id="unique-escrow-test",
            consumer_id=consumer["id"],
            provider_id=provider["id"],
            amount=1.0,
        )
