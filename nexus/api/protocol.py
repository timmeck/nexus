"""Protocol API — Core message handling endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from nexus.models.protocol import NexusRequest, NexusResponse
from nexus.models.verification import VerificationRequest, VerificationResult
from nexus.protocol import handler
from nexus.verification import service as verification

router = APIRouter(prefix="/api/protocol", tags=["protocol"])


@router.post("/request", response_model=NexusResponse)
async def submit_request(request: NexusRequest):
    """Submit a NexusRequest — routes to best agent and returns response."""
    return await handler.handle_request(request)


@router.post("/verify", response_model=VerificationResult)
async def verify_request(request: VerificationRequest):
    """Send same query to multiple agents and compare responses.

    Returns consensus score, best answer, and detected contradictions.
    """
    result = await verification.verify(request)

    # Store verification result
    from nexus.database import get_db, to_json

    db = await get_db()
    await db.execute(
        """INSERT INTO verifications
           (verification_id, query, capability, agents_queried, agents_responded,
            consensus, consensus_score, best_answer, contradictions, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.verification_id,
            result.query,
            result.capability,
            result.agents_queried,
            result.agents_responded,
            int(result.consensus),
            result.consensus_score,
            result.best_answer,
            to_json(result.contradictions),
            result.created_at.isoformat(),
        ),
    )
    await db.commit()

    return result


@router.get("/verifications")
async def list_verifications(limit: int = 20):
    """Get recent verification results."""
    from nexus.database import from_json, get_db

    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM verifications ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    results = []
    for r in await rows.fetchall():
        results.append(
            {
                "verification_id": r["verification_id"],
                "query": r["query"],
                "capability": r["capability"],
                "agents_queried": r["agents_queried"],
                "agents_responded": r["agents_responded"],
                "consensus": bool(r["consensus"]),
                "consensus_score": r["consensus_score"],
                "best_answer": r["best_answer"],
                "contradictions": from_json(r["contradictions"]),
                "created_at": r["created_at"],
            }
        )
    return {"verifications": results, "count": len(results)}


@router.get("/active")
async def active_requests():
    """Get currently active (in-flight) requests."""
    return {"active": handler.get_active_requests()}
