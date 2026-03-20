"""A2A (Agent-to-Agent) Compatibility Layer — Agent Card endpoints.

Implements the A2A protocol's Agent Card discovery mechanism so that
external A2A-compatible agents can discover Nexus and its registered agents.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nexus import __version__
from nexus.registry import service as registry

router = APIRouter(tags=["a2a"])


@router.get("/.well-known/agent.json")
async def gateway_agent_card():
    """Return the A2A Agent Card for the Nexus gateway itself.

    Capabilities are populated dynamically from all registered agents.
    """
    agents = await registry.list_agents()
    # Collect unique capability names across all agents
    capability_names: set[str] = set()
    for agent in agents:
        for cap in agent.capabilities:
            capability_names.add(cap.name)

    # Always include core Nexus capabilities
    capability_names.add("verification")

    capabilities = sorted(
        [{"name": name} for name in capability_names],
        key=lambda c: c["name"],
    )

    return {
        "name": "Nexus Protocol Gateway",
        "description": "AI-to-AI trust enforcement and routing",
        "url": "http://localhost:9500",
        "version": __version__,
        "capabilities": capabilities,
        "protocol": "a2a/1.0",
        "authentication": {"type": "bearer"},
    }


@router.get("/api/agents/{agent_id}/card")
async def agent_card(agent_id: str):
    """Return an A2A-compatible Agent Card for a specific registered agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    capabilities = [{"name": cap.name} for cap in agent.capabilities]

    return {
        "name": agent.name,
        "description": agent.description,
        "url": agent.endpoint,
        "version": "1.0.0",
        "capabilities": capabilities,
        "protocol": "a2a/1.0",
        "authentication": {"type": "bearer"} if agent.auth_enabled else {"type": "none"},
        "nexus": {
            "agent_id": agent.id,
            "trust_score": agent.trust_score,
            "status": agent.status.value,
        },
    }
