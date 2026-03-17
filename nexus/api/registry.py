"""Registry API — Agent discovery and management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from nexus.models.agent import Agent, AgentCreate, AgentStatus, AgentUpdate
from nexus.registry import service

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.post("/agents", status_code=201)
async def register_agent(payload: AgentCreate):
    """Register a new agent in the Nexus network.

    Returns the full agent record including the API key (shown only once).
    """
    try:
        agent = await service.register_agent(payload)
        # Return with API key visible (only time it's shown)
        data = agent.model_dump(mode="json")
        return data
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/agents")
async def list_agents(
    status: AgentStatus | None = Query(None),
    capability: str | None = Query(None),
    tag: str | None = Query(None),
):
    """List registered agents with optional filters."""
    agents = await service.list_agents(status=status, capability=capability, tag=tag)
    # Hide API keys in public listings
    return [_sanitize_agent(a) for a in agents]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get a specific agent by ID."""
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _sanitize_agent(agent)


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
                "auth_enabled": a.auth_enabled,
                "capabilities": [c.model_dump() for c in a.capabilities if c.name.lower() == capability.lower()],
            }
            for a in agents
        ],
    }


@router.get("/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    """Full health assessment for an agent.

    Not just "online" — but alive, trusted, solvent, policy-valid.
    """
    agent = await service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from nexus.payments.service import get_balance

    balance = await get_balance(agent_id)

    # Determine health dimensions
    alive = agent.status in (AgentStatus.ONLINE, AgentStatus.DEGRADED)
    trusted = agent.trust_score >= 0.3
    solvent = balance >= 1.0
    mature = agent.total_interactions >= 5

    # Overall health
    healthy = alive and trusted and solvent

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "status": agent.status,
        "health": {
            "alive": alive,
            "trusted": trusted,
            "solvent": solvent,
            "mature": mature,
            "healthy": healthy,
        },
        "details": {
            "trust_score": agent.trust_score,
            "balance": balance,
            "total_interactions": agent.total_interactions,
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        },
    }


def _sanitize_agent(agent: Agent) -> dict:
    """Return agent data with API key hidden."""
    data = agent.model_dump(mode="json")
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:8] + "..." + data["api_key"][-4:]
    return data
