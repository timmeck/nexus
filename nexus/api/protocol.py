"""Protocol API — Core message handling endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nexus.models.protocol import NexusRequest, NexusResponse
from nexus.models.verification import VerificationRequest, VerificationResult
from nexus.protocol import handler
from nexus.verification import service as verification

router = APIRouter(prefix="/api/protocol", tags=["protocol"])


class AsyncNexusRequest(NexusRequest):
    """NexusRequest with optional async flag."""

    async_mode: bool = False


@router.post("/request")
async def submit_request(request: AsyncNexusRequest):
    """Submit a NexusRequest — routes to best agent and returns response.

    If async_mode is true, returns a task_id immediately for polling.
    """
    if request.async_mode:
        # Convert back to base NexusRequest for the handler
        base_request = NexusRequest(**request.model_dump(exclude={"async_mode"}))
        return await handler.handle_request_async(base_request)
    return await handler.handle_request(request)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Poll for the result of an async task."""
    result = handler.get_async_task_status(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return result


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


@router.get("/requests/{request_id}/events")
async def get_request_events(request_id: str):
    """Get persistent audit trail for a request."""
    from nexus.database import get_db

    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM request_events WHERE request_id = ? ORDER BY created_at",
        (request_id,),
    )
    events = []
    for r in await rows.fetchall():
        events.append(
            {
                "event_id": r["event_id"],
                "request_id": r["request_id"],
                "step": r["step"],
                "from_state": r["from_state"],
                "to_state": r["to_state"],
                "actor": r["actor"],
                "details": r["details"],
                "created_at": r["created_at"],
            }
        )
    return {"events": events, "count": len(events)}


@router.get("/active")
async def active_requests():
    """Get currently active (in-flight) requests."""
    return {"active": handler.get_active_requests()}
