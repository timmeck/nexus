"""Tests for the Reconciliation job — stuck request and orphaned escrow detection."""

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
    assert results["stuck_events_found"] == 0
    assert results["orphaned_escrows_released"] == 0
    assert results["orphaned_escrows_expired"] == 0


@pytest.mark.asyncio
async def test_reconcile_detects_stuck_request(client: AsyncClient):
    """Request with old events and no terminal state should be flagged."""
    from nexus.database import get_db
    from nexus.protocol.reconciliation import reconcile_once

    db = await get_db()
    old_time = (datetime.utcnow() - timedelta(seconds=600)).isoformat()

    # Simulate a stuck request — has "received" event but no terminal event
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-stuck-1", "stuck-req-1", "received", "", "received", "system", "{}", old_time),
    )
    await db.execute(
        """INSERT INTO request_events
           (event_id, request_id, step, from_state, to_state, actor, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("ev-stuck-2", "stuck-req-1", "routing", "received", "routing", "system", "{}", old_time),
    )
    await db.commit()

    results = await reconcile_once()
    assert results["stuck_events_found"] >= 1


@pytest.mark.asyncio
async def test_reconcile_ignores_completed_requests(client: AsyncClient):
    """Request with terminal event should NOT be flagged as stuck."""
    from nexus.database import get_db
    from nexus.protocol.reconciliation import reconcile_once

    db = await get_db()
    old_time = (datetime.utcnow() - timedelta(seconds=600)).isoformat()

    # Request that completed normally
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
    assert results["stuck_events_found"] == 0


@pytest.mark.asyncio
async def test_reconcile_releases_mature_escrows(client: AsyncClient):
    """Escrows past settlement window should be released."""
    from nexus.defense.service import create_escrow

    consumer = await create_agent(
        client,
        {"name": "recon-consumer", "endpoint": "http://localhost:19900", "capabilities": []},
    )
    provider = await create_agent(
        client,
        {"name": "recon-provider", "endpoint": "http://localhost:19901", "capabilities": []},
    )

    # Create escrow with past release time
    from nexus.database import get_db

    escrow = await create_escrow(
        request_id="recon-test-1",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=2.0,
    )

    # Manually set release_at to the past
    db = await get_db()
    past = (datetime.utcnow() - timedelta(seconds=120)).isoformat()
    await db.execute(
        "UPDATE escrow SET release_at = ? WHERE escrow_id = ?",
        (past, escrow["escrow_id"]),
    )
    await db.commit()

    from nexus.protocol.reconciliation import reconcile_once

    results = await reconcile_once()
    assert results["orphaned_escrows_released"] >= 1


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

    # First escrow — should succeed
    await create_escrow(
        request_id="unique-escrow-test",
        consumer_id=consumer["id"],
        provider_id=provider["id"],
        amount=1.0,
    )

    # Second escrow with same request_id — should fail (unique constraint)
    with pytest.raises(sqlite3.IntegrityError):
        await create_escrow(
            request_id="unique-escrow-test",
            consumer_id=consumer["id"],
            provider_id=provider["id"],
            amount=1.0,
        )
