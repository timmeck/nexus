"""Reconciliation — classifies, repairs, and audits stuck/orphaned state.

Not just detection. Classification → Idempotent Repair → Audit Trail.
Every repair action must be safe to run twice without double effects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

log = logging.getLogger("nexus.reconciliation")

RECONCILIATION_INTERVAL_SECONDS = 60
STUCK_REQUEST_TIMEOUT_SECONDS = 300  # 5 minutes


# ── Stuck Class Taxonomy ────────────────────────────────────


class StuckClass:
    """Classification for stuck/orphaned states."""

    MATURE_ESCROW = "mature_escrow"  # Past settlement window → auto-release
    ORPHANED_ESCROW = "orphaned_escrow"  # Terminal request + held escrow → auto-refund
    STUCK_REQUEST = "stuck_request"  # Old events, no terminal → alert-only


# Action types
ACTION_AUTO_RELEASE = "auto_release"
ACTION_AUTO_REFUND = "auto_refund"
ACTION_ALERT_ONLY = "alert_only"


async def reconcile_once() -> dict:
    """Single reconciliation pass with classification and idempotent repair.

    Returns summary of detections, classifications, and repairs.
    """
    from nexus.database import get_db
    from nexus.defense.service import dispute_escrow, release_mature_escrows

    results = {
        "mature_escrows_released": 0,
        "orphaned_escrows_refunded": 0,
        "stuck_requests_found": 0,
        "repairs": [],
    }

    try:
        db = await get_db()

        # ── Class 1: Mature escrows (past settlement window) ──
        released = await release_mature_escrows()
        results["mature_escrows_released"] = released
        if released > 0:
            await _audit_reconciliation(
                db,
                stuck_class=StuckClass.MATURE_ESCROW,
                action=ACTION_AUTO_RELEASE,
                count=released,
                details={"window_seconds": 60},
            )
            results["repairs"].append(
                {
                    "class": StuckClass.MATURE_ESCROW,
                    "action": ACTION_AUTO_RELEASE,
                    "count": released,
                }
            )

        # ── Class 2: Orphaned escrows (terminal request + held escrow) ──
        rows = await db.execute(
            """SELECT e.escrow_id, e.request_id, e.amount, e.consumer_id
               FROM escrow e
               WHERE e.status = 'held'
               AND e.request_id IN (
                   SELECT request_id FROM request_events
                   WHERE step IN ('error', 'provider_failed')
               )""",
        )
        orphaned = await rows.fetchall()
        results["orphaned_escrows_refunded"] = len(orphaned)

        for esc in orphaned:
            # Idempotent: dispute_escrow checks status='held' — won't double-refund
            result = await dispute_escrow(
                esc["escrow_id"],
                reason=f"Reconciliation: orphaned escrow for failed request {esc['request_id']}",
            )
            if "error" not in result:
                log.info(
                    "Reconciler refunded orphaned escrow %s (%.4f credits) for request %s",
                    esc["escrow_id"],
                    esc["amount"],
                    esc["request_id"],
                )

        if orphaned:
            await _audit_reconciliation(
                db,
                stuck_class=StuckClass.ORPHANED_ESCROW,
                action=ACTION_AUTO_REFUND,
                count=len(orphaned),
                details={"escrow_ids": [e["escrow_id"] for e in orphaned]},
            )
            results["repairs"].append(
                {
                    "class": StuckClass.ORPHANED_ESCROW,
                    "action": ACTION_AUTO_REFUND,
                    "count": len(orphaned),
                }
            )

        # ── Class 3: Stuck requests (old, no terminal event) ──
        threshold = (datetime.utcnow() - timedelta(seconds=STUCK_REQUEST_TIMEOUT_SECONDS)).isoformat()

        rows = await db.execute(
            """SELECT DISTINCT re.request_id, MAX(re.created_at) as last_event,
                      MAX(re.step) as last_step
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
        results["stuck_requests_found"] = len(stuck)

        if stuck:
            stuck_ids = []
            for row in stuck:
                log.warning(
                    "Stuck request: %s (last step: %s, last event: %s) — alert only",
                    row["request_id"],
                    row["last_step"],
                    row["last_event"],
                )
                stuck_ids.append(row["request_id"])

            await _audit_reconciliation(
                db,
                stuck_class=StuckClass.STUCK_REQUEST,
                action=ACTION_ALERT_ONLY,
                count=len(stuck),
                details={"request_ids": stuck_ids},
            )
            results["repairs"].append(
                {
                    "class": StuckClass.STUCK_REQUEST,
                    "action": ACTION_ALERT_ONLY,
                    "count": len(stuck),
                }
            )

    except Exception as e:
        log.debug("Reconciliation error: %s", e)

    if any(v for k, v in results.items() if k != "repairs" and v):
        log.info("Reconciliation complete: %s", {k: v for k, v in results.items() if k != "repairs"})

    return results


async def _audit_reconciliation(
    db,
    stuck_class: str,
    action: str,
    count: int,
    details: dict | None = None,
) -> None:
    """Write reconciliation audit event. Actor = reconciler."""
    try:
        await db.execute(
            """INSERT INTO request_events
               (event_id, request_id, step, from_state, to_state, actor, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                f"reconciliation-{uuid.uuid4().hex[:8]}",
                f"reconcile_{stuck_class}",
                "",
                action,
                "reconciler",
                json.dumps({"class": stuck_class, "action": action, "count": count, **(details or {})}),
                datetime.now(UTC).isoformat(),
            ),
        )
        await db.commit()
    except Exception:
        log.debug("Failed to write reconciliation audit event")


async def reconciliation_loop() -> None:
    """Background task: run reconciliation periodically."""
    while True:
        try:
            await reconcile_once()
        except Exception as e:
            log.debug("Reconciliation cycle error: %s", e)

        await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)
