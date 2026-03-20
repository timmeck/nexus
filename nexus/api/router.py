"""Router API — Query routing and agent matching endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from nexus.models.protocol import NexusRequest  # noqa: TC001 (runtime: FastAPI param)
from nexus.router import service

router = APIRouter(prefix="/api/router", tags=["router"])


@router.post("/route")
async def route_request(
    request: NexusRequest,
    strategy: str = Query("best", pattern="^(best|cheapest|fastest|trusted)$"),
):
    """Find the best agent(s) for a request without executing it."""
    results = await service.route(request, strategy=strategy)
    return {
        "request_id": request.request_id,
        "strategy": strategy,
        "candidates": [r.to_dict() for r in results],
    }


@router.get("/health")
async def agent_health(agent_id: str | None = None):
    """Get health metrics for agents used in routing decisions."""
    return {"health": service.get_agent_health(agent_id)}
