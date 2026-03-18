"""Trust Layer — Reputation scoring and interaction tracking."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from nexus.config import (
    MAX_TRUST,
    MIN_TRUST,
    TRUST_PENALTY,
    TRUST_REWARD,
)
from nexus.database import get_db
from nexus.models.trust import InteractionRecord, TrustReport

log = logging.getLogger("nexus.trust")


async def record_interaction(
    request_id: str,
    consumer_id: str,
    provider_id: str,
    success: bool,
    confidence: float = 0.0,
    verified: bool = False,
    cost: float = 0.0,
    response_ms: int = 0,
) -> InteractionRecord:
    """Record an interaction and update trust scores."""
    db = await get_db()
    interaction_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO interactions
           (interaction_id, request_id, consumer_id, provider_id,
            success, confidence, verified, cost, response_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            interaction_id,
            request_id,
            consumer_id,
            provider_id,
            int(success),
            confidence,
            int(verified),
            cost,
            response_ms,
            now,
        ),
    )

    # Update agent stats
    await db.execute(
        """UPDATE agents
           SET total_interactions = total_interactions + 1,
               successful_interactions = successful_interactions + ?
           WHERE id = ?""",
        (int(success), provider_id),
    )

    # Update trust score
    delta = TRUST_REWARD if success else -TRUST_PENALTY
    # Bonus for high confidence on verified interactions
    if verified and success and confidence > 0.8:
        delta += TRUST_REWARD * 0.5

    # Get trust before update
    row = await db.execute("SELECT trust_score FROM agents WHERE id = ?", (provider_id,))
    agent_row = await row.fetchone()
    trust_before = agent_row["trust_score"] if agent_row else 0.5

    await db.execute(
        """UPDATE agents
           SET trust_score = MAX(?, MIN(?, trust_score + ?))
           WHERE id = ?""",
        (MIN_TRUST, MAX_TRUST, delta, provider_id),
    )

    trust_after = max(MIN_TRUST, min(MAX_TRUST, trust_before + delta))

    # Record in trust ledger (append-only, idempotent per agent+request)
    reason = "success" if success else "failure"
    if verified and success and confidence > 0.8:
        reason = "verified_success"
    ledger_id = uuid.uuid4().hex[:12]
    await db.execute(
        """INSERT OR IGNORE INTO trust_ledger
           (entry_id, agent_id, request_id, delta, reason, trust_before, trust_after, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ledger_id, provider_id, request_id, delta, reason, trust_before, trust_after, now),
    )

    await db.commit()
    log.info(
        "Interaction %s: provider=%s success=%s trust %.3f → %.3f (Δ%.3f)",
        interaction_id,
        provider_id,
        success,
        trust_before,
        trust_after,
        delta,
    )

    return InteractionRecord(
        interaction_id=interaction_id,
        request_id=request_id,
        consumer_id=consumer_id,
        provider_id=provider_id,
        success=success,
        confidence=confidence,
        verified=verified,
        cost=cost,
        response_ms=response_ms,
        created_at=datetime.fromisoformat(now),
    )


async def get_trust_report(agent_id: str) -> TrustReport | None:
    """Generate a trust report for an agent."""
    db = await get_db()

    # Get agent info
    row = await db.execute(
        "SELECT id, name, trust_score, total_interactions, successful_interactions FROM agents WHERE id = ?",
        (agent_id,),
    )
    agent = await row.fetchone()
    if not agent:
        return None

    total = agent["total_interactions"]
    successful = agent["successful_interactions"]
    success_rate = successful / total if total > 0 else 0.0

    # Get interaction stats
    row = await db.execute(
        """SELECT COALESCE(AVG(confidence), 0) as avg_conf,
                  COALESCE(AVG(response_ms), 0) as avg_ms,
                  COALESCE(SUM(cost), 0) as total_cost
           FROM interactions WHERE provider_id = ?""",
        (agent_id,),
    )
    stats = await row.fetchone()

    return TrustReport(
        agent_id=agent["id"],
        agent_name=agent["name"],
        trust_score=agent["trust_score"],
        total_interactions=total,
        successful_interactions=successful,
        success_rate=success_rate,
        avg_confidence=stats["avg_conf"],
        avg_response_ms=stats["avg_ms"],
        total_earned=stats["total_cost"],
    )


async def get_trust_ledger(agent_id: str, limit: int = 50) -> list[dict]:
    """Get append-only trust ledger for an agent."""
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM trust_ledger WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, limit),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_interaction_history(
    agent_id: str,
    limit: int = 50,
) -> list[InteractionRecord]:
    """Get recent interactions for an agent."""
    db = await get_db()
    rows = await db.execute(
        """SELECT * FROM interactions
           WHERE provider_id = ? OR consumer_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (agent_id, agent_id, limit),
    )
    return [
        InteractionRecord(
            interaction_id=r["interaction_id"],
            request_id=r["request_id"],
            consumer_id=r["consumer_id"],
            provider_id=r["provider_id"],
            success=bool(r["success"]),
            confidence=r["confidence"],
            verified=bool(r["verified"]),
            cost=r["cost"],
            response_ms=r["response_ms"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in await rows.fetchall()
    ]
