"""Policy API — Enterprise policy layer endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nexus.policy import service as policy

router = APIRouter(prefix="/api/policy", tags=["policy"])


# ── Models ────────────────────────────────────────────────────────


class LocalityRequest(BaseModel):
    agent_id: str
    region: str = Field(..., description="e.g. 'eu', 'us', 'asia', 'global'")
    jurisdiction: str = Field("none", description="e.g. 'gdpr', 'hipaa', 'none'")
    datacenter: str = ""
    country_code: str = Field("", description="ISO 3166-1 alpha-2, e.g. 'DE', 'US'")


class ComplianceRequest(BaseModel):
    agent_id: str
    claim_type: str = Field(..., description="e.g. 'no_training_on_prompts', 'gdpr_compliant'")
    claim_value: str = "true"
    description: str = ""
    expires_at: str | None = None


class PolicyCreateRequest(BaseModel):
    name: str
    description: str = ""
    rules: dict = Field(..., description="Routing rules: require_region, require_compliance, etc.")
    priority: int = 0


class GatewayRequest(BaseModel):
    name: str
    gateway_type: str = Field(..., description="e.g. 'kong', 'tyk', 'dreamfactory', 'nginx'")
    endpoint: str
    settings: dict = Field(default_factory=dict)


# ── Data Locality ─────────────────────────────────────────────────


@router.post("/locality")
async def set_locality(body: LocalityRequest):
    """Set geographic/jurisdiction info for an agent."""
    return await policy.set_agent_locality(
        agent_id=body.agent_id,
        region=body.region,
        jurisdiction=body.jurisdiction,
        datacenter=body.datacenter,
        country_code=body.country_code,
    )


@router.get("/locality/{agent_id}")
async def get_locality(agent_id: str):
    """Get locality info for an agent."""
    loc = await policy.get_agent_locality(agent_id)
    if not loc:
        raise HTTPException(404, "No locality set for this agent")
    return loc


@router.get("/localities")
async def list_localities():
    """List all agent localities."""
    locs = await policy.list_localities()
    return {"localities": locs, "count": len(locs)}


# ── Compliance Claims ─────────────────────────────────────────────


@router.get("/compliance/types")
async def list_claim_types():
    """List standard compliance claim types."""
    return {"claim_types": policy.CLAIM_TYPES}


@router.post("/compliance")
async def add_claim(body: ComplianceRequest):
    """Agent declares a compliance claim."""
    return await policy.add_compliance_claim(
        agent_id=body.agent_id,
        claim_type=body.claim_type,
        claim_value=body.claim_value,
        description=body.description,
        expires_at=body.expires_at,
    )


@router.get("/compliance/{agent_id}")
async def get_claims(agent_id: str):
    """Get all compliance claims for an agent."""
    claims = await policy.get_agent_claims(agent_id)
    return {"claims": claims, "count": len(claims)}


@router.post("/compliance/{claim_id}/verify")
async def verify_claim(claim_id: str):
    """Mark a compliance claim as verified."""
    return await policy.verify_claim(claim_id)


# ── Routing Policies ──────────────────────────────────────────────


@router.post("/routing")
async def create_policy(body: PolicyCreateRequest):
    """Create a routing policy with locality/compliance rules."""
    return await policy.create_routing_policy(
        name=body.name,
        rules=body.rules,
        description=body.description,
        priority=body.priority,
    )


@router.get("/routing")
async def list_policies(enabled_only: bool = False):
    """List routing policies."""
    policies = await policy.list_policies(enabled_only=enabled_only)
    return {"policies": policies, "count": len(policies)}


@router.get("/routing/{policy_id}")
async def get_policy(policy_id: str):
    """Get a specific routing policy."""
    p = await policy.get_policy(policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    return p


@router.post("/routing/{policy_id}/toggle")
async def toggle_policy(policy_id: str):
    """Enable/disable a routing policy."""
    return await policy.toggle_policy(policy_id)


@router.delete("/routing/{policy_id}")
async def delete_policy(policy_id: str):
    """Delete a routing policy."""
    if not await policy.delete_policy(policy_id):
        raise HTTPException(404, "Policy not found")
    return {"status": "deleted"}


# ── Edge Gateways ─────────────────────────────────────────────────


@router.post("/gateways")
async def add_gateway(body: GatewayRequest):
    """Register an edge gateway."""
    return await policy.add_gateway(
        name=body.name,
        gateway_type=body.gateway_type,
        endpoint=body.endpoint,
        settings=body.settings,
    )


@router.get("/gateways")
async def list_gateways():
    """List all gateway configurations."""
    gateways = await policy.list_gateways()
    return {"gateways": gateways, "count": len(gateways)}


@router.delete("/gateways/{config_id}")
async def delete_gateway(config_id: str):
    """Remove a gateway configuration."""
    if not await policy.delete_gateway(config_id):
        raise HTTPException(404, "Gateway not found")
    return {"status": "deleted"}


# ── Audit Trail ───────────────────────────────────────────────────


@router.get("/audit")
async def audit_log(event_type: str | None = None, agent_id: str | None = None, limit: int = 100):
    """Query the audit trail."""
    events = await policy.get_audit_log(event_type=event_type, agent_id=agent_id, limit=limit)
    return {"events": events, "count": len(events)}


# ── Stats ─────────────────────────────────────────────────────────


@router.get("/stats")
async def policy_stats():
    """Get policy layer statistics."""
    return await policy.get_policy_stats()
