"""Defense API — Adversarial defense endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from nexus.defense import service as defense

router = APIRouter(prefix="/api/defense", tags=["defense"])


# ── Models ────────────────────────────────────────────────────────


class SlashRequest(BaseModel):
    agent_id: str
    request_id: str
    reason: str
    claimed_confidence: float = Field(0.0, ge=0.0, le=1.0)
    actual_quality: float = Field(0.0, ge=0.0, le=1.0)


class ChallengeRequest(BaseModel):
    request_id: str
    challenger_id: str
    target_id: str
    reason: str = ""


class ChallengeResolve(BaseModel):
    upheld: bool
    ruling: str = ""


class DisputeRequest(BaseModel):
    reason: str = ""


# ── Slashing ──────────────────────────────────────────────────────


@router.post("/slash")
async def slash_agent(body: SlashRequest):
    """Slash an agent for bad output — loses trust and credits."""
    return await defense.slash_agent(
        agent_id=body.agent_id,
        request_id=body.request_id,
        reason=body.reason,
        claimed_confidence=body.claimed_confidence,
        actual_quality=body.actual_quality,
    )


@router.get("/slashes")
async def slashing_history(agent_id: str | None = None, limit: int = 50):
    """Get slashing log."""
    return {"slashes": await defense.get_slashing_history(agent_id=agent_id, limit=limit)}


# ── Escrow ────────────────────────────────────────────────────────


@router.get("/escrows")
async def list_escrows(status: str | None = None, limit: int = 50):
    """List escrow records."""
    return {"escrows": await defense.list_escrows(status=status, limit=limit)}


@router.post("/escrows/{escrow_id}/release")
async def release_escrow(escrow_id: str):
    """Manually release an escrow (funds go to provider)."""
    return await defense.release_escrow(escrow_id)


@router.post("/escrows/{escrow_id}/dispute")
async def dispute_escrow(escrow_id: str, body: DisputeRequest):
    """Dispute an escrow — funds returned to consumer, provider slashed."""
    return await defense.dispute_escrow(escrow_id, reason=body.reason)


@router.post("/escrows/release-mature")
async def release_mature():
    """Release all escrows past their settlement window."""
    count = await defense.release_mature_escrows()
    return {"released": count}


# ── Challenges ────────────────────────────────────────────────────


@router.post("/challenges")
async def create_challenge(body: ChallengeRequest):
    """Challenge another agent's output. Costs a fee."""
    return await defense.create_challenge(
        request_id=body.request_id,
        challenger_id=body.challenger_id,
        target_id=body.target_id,
        reason=body.reason,
    )


@router.post("/challenges/{challenge_id}/resolve")
async def resolve_challenge(challenge_id: str, body: ChallengeResolve):
    """Resolve a challenge — uphold or reject."""
    return await defense.resolve_challenge(
        challenge_id=challenge_id,
        upheld=body.upheld,
        ruling=body.ruling,
    )


@router.get("/challenges")
async def list_challenges(status: str | None = None, limit: int = 50):
    """List challenges."""
    return {"challenges": await defense.list_challenges(status=status, limit=limit)}


# ── Sybil Detection ──────────────────────────────────────────────


@router.get("/sybil/rate")
async def registration_rate():
    """Check if registration rate is suspicious."""
    return await defense.check_registration_rate()


@router.get("/sybil/maturity/{agent_id}")
async def agent_maturity(agent_id: str):
    """Check if an agent has enough history to be trusted."""
    return await defense.check_agent_maturity(agent_id)


@router.get("/sybil/clusters")
async def sybil_clusters():
    """Detect agents with suspiciously similar capabilities."""
    clusters = await defense.detect_sybil_clusters()
    return {"clusters": clusters, "count": len(clusters)}


# ── Stats ─────────────────────────────────────────────────────────


@router.get("/stats")
async def defense_stats():
    """Get aggregate defense statistics."""
    return await defense.get_defense_stats()
