"""Registry API — Agent discovery and management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from nexus.models.agent import Agent, AgentCreate, AgentStatus, AgentUpdate
from nexus.registry import service

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.post("/agents", response_model=Agent, status_code=201)
async def register_agent(payload: AgentCreate):
    """Register a new agent in the Nexus network."""
    try:
        return await service.register_agent(payload)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/agents", response_model=list[Agent])
async def list_agents(
    status: AgentStatus | None = Query(None),
    capability: str | None = Query(None),
    tag: str | None = Query(None),
):
    """List registered agents with optional filters."""
    return await service.list_agents(status=status, capability=capability, tag=tag)


@router.get("/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    """Get a specific agent by ID."""
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/agents/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, payload: AgentUpdate):
    """Update an agent's details."""
    agent = await service.update_agent(agent_id, payload)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    """Unregister an agent from the network."""
    deleted = await service.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/agents/{agent_id}/heartbeat")
async def heartbeat(agent_id: str):
    """Update agent heartbeat — confirms the agent is alive."""
    ok = await service.heartbeat(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "ok", "agent_id": agent_id}


@router.get("/discover")
async def discover(
    capability: str = Query(..., description="Capability to search for"),
    language: str | None = Query(None),
    min_trust: float = Query(0.0, ge=0.0, le=1.0),
):
    """Discover agents by capability — the DNS lookup for AI."""
    agents = await service.find_by_capability(
        capability=capability,
        language=language,
        min_trust=min_trust,
    )
    return {
        "capability": capability,
        "count": len(agents),
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "endpoint": a.endpoint,
                "trust_score": a.trust_score,
                "capabilities": [c.model_dump() for c in a.capabilities if c.name.lower() == capability.lower()],
            }
            for a in agents
        ],
    }
