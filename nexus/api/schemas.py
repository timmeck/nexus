"""Capability Schema API — Browse and validate agent capability schemas."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nexus.models.capability_schema import (
    SCHEMA_TEMPLATES,
    AgentCapabilitySpec,
    CapabilitySchema,
)
from nexus.registry import service as registry

router = APIRouter(prefix="/api/schemas", tags=["schemas"])


@router.get("/templates")
async def list_templates():
    """List all built-in capability schema templates."""
    return {
        "templates": {name: schema.model_dump() for name, schema in SCHEMA_TEMPLATES.items()},
        "count": len(SCHEMA_TEMPLATES),
    }


@router.get("/templates/{capability_name}")
async def get_template(capability_name: str):
    """Get a specific capability schema template."""
    schema = SCHEMA_TEMPLATES.get(capability_name)
    if not schema:
        raise HTTPException(404, f"No template for capability: {capability_name}")
    return schema.model_dump()


@router.get("/agents/{agent_id}")
async def get_agent_spec(agent_id: str):
    """Get the full capability spec for an agent (like OpenAPI for agent skills)."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    schemas = []
    for cap in agent.capabilities:
        # Use template if available, otherwise build from agent data
        template = SCHEMA_TEMPLATES.get(cap.name)
        if template:
            schema = template.model_copy(
                update={
                    "price_per_request": cap.price_per_request,
                    "avg_response_ms": cap.avg_response_ms,
                    "languages": cap.languages,
                }
            )
        else:
            schema = CapabilitySchema(
                name=cap.name,
                description=cap.description,
                price_per_request=cap.price_per_request,
                avg_response_ms=cap.avg_response_ms,
                languages=cap.languages,
                input_schema=cap.input_schema
                or {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                output_schema=cap.output_schema
                or {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
            )
        schemas.append(schema)

    spec = AgentCapabilitySpec(
        agent_name=agent.name,
        description=agent.description,
        base_url=agent.endpoint,
        capabilities=schemas,
    )
    return spec.model_dump()


@router.get("/discover")
async def discover_by_schema(
    category: str | None = None,
    tag: str | None = None,
):
    """Discover capabilities across all agents by category or tag."""
    agents = await registry.list_agents()
    results = []

    for agent in agents:
        for cap in agent.capabilities:
            template = SCHEMA_TEMPLATES.get(cap.name)

            # Filter by category
            if category and template:
                if template.category.lower() != category.lower():
                    continue
            elif category and not template:
                continue

            # Filter by tag
            if tag and template:
                if tag.lower() not in [t.lower() for t in template.tags]:
                    continue
            elif tag and not template:
                continue

            results.append(
                {
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_endpoint": agent.endpoint,
                    "capability": cap.name,
                    "description": cap.description or (template.description if template else ""),
                    "category": template.category if template else "general",
                    "price": cap.price_per_request,
                    "avg_ms": cap.avg_response_ms,
                    "languages": cap.languages,
                    "trust_score": agent.trust_score,
                    "has_schema": template is not None,
                }
            )

    return {"capabilities": results, "count": len(results)}


@router.get("/categories")
async def list_categories():
    """List all capability categories from templates."""
    categories = set()
    for schema in SCHEMA_TEMPLATES.values():
        categories.add(schema.category)
    return {"categories": sorted(categories)}
