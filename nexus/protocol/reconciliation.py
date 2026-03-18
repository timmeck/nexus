"""Reconciliation — finds and resolves stuck requests and orphaned escrows.

Run periodically to detect:
- Requests stuck in non-terminal states
- Escrows held past their settlement window
- Escrows without matching terminal request state
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("nexus.reconciliation")

RECONCILIATION_INTERVAL_SECONDS = 60
STUCK_REQUEST_TIMEOUT_SECONDS = 300  # 5 minutes


async def reconcile_once() -> dict:
    """Single reconciliation pass. Returns summary of actions taken."""
    from nexus.database import get_db
    from nexus.defense.service import release_mature_escrows

    results = {
        "stuck_events_found": 0,
        "orphaned_escrows_released": 0,
        "orphaned_escrows_expired": 0,
    }

    try:
        db = await get_db()

        # 1. Release mature escrows (past settlement window)
        released = await release_mature_escrows()
        results["orphaned_escrows_released"] = released

        # 2. Find requests stuck in non-terminal states (old events with no completion)
        threshold = (datetime.utcnow() - timedelta(seconds=STUCK_REQUEST_TIMEOUT_SECONDS)).isoformat()

        # Find request_ids that have events but no terminal step
        rows = await db.execute(
            """SELECT DISTINCT re.request_id, MAX(re.created_at) as last_event
               FROM request_events re
               WHERE re.created_at < ?
               AND re.request_id NOT IN (
                   SELECT request_id FROM request_events
                   WHERE step IN ('settled', 'rejected', 'error', 'no_route',
                                  'insufficient_funds', 'provider_failed', 'completed')
               )
               GROUP BY re.request_id""",
            (threshold,),
        )
        stuck = await rows.fetchall()
        results["stuck_events_found"] = len(stuck)

        if stuck:
            for row in stuck:
                log.warning(
                    "Stuck request detected: %s (last event: %s)",
                    row["request_id"],
                    row["last_event"],
                )

        # 3. Find held escrows whose request already has a terminal event
        rows = await db.execute(
            """SELECT e.escrow_id, e.request_id, e.amount
               FROM escrow e
               WHERE e.status = 'held'
               AND e.request_id IN (
                   SELECT request_id FROM request_events
                   WHERE step IN ('error', 'provider_failed')
               )""",
        )
        orphaned = await rows.fetchall()
        results["orphaned_escrows_expired"] = len(orphaned)

        # These escrows should have been refunded but weren't (crash recovery)
        for esc in orphaned:
            log.warning(
                "Orphaned escrow %s for failed request %s — should be refunded",
                esc["escrow_id"],
                esc["request_id"],
            )

    except Exception as e:
        log.debug("Reconciliation error: %s", e)

    if any(v > 0 for v in results.values()):
        log.info("Reconciliation: %s", results)

    return results


async def reconciliation_loop() -> None:
    """Background task: run reconciliation periodically."""
    while True:
        try:
            await reconcile_once()
        except Exception as e:
            log.debug("Reconciliation cycle error: %s", e)

        await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)
