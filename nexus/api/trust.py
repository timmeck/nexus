"""Trust API — Reputation and interaction tracking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from nexus.trust import service

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get("/report/{agent_id}")
async def trust_report(agent_id: str):
    """Get trust report for an agent."""
    report = await service.get_trust_report(agent_id)
    if not report:
        raise HTTPException(status_code=404, detail="Agent not found")
    return report


@router.get("/history/{agent_id}")
async def interaction_history(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get interaction history for an agent."""
    return await service.get_interaction_history(agent_id, limit=limit)
