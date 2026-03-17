"""Tests for Capability Schema Standard."""

from __future__ import annotations

import pytest

from tests.conftest import create_agent


async def _ensure_tables():
    from nexus.federation.service import ensure_tables

    await ensure_tables()
    from nexus.payments.service import ensure_tables as ensure_payment_tables

    await ensure_payment_tables()


@pytest.mark.asyncio
async def test_list_templates(client):
    """Should return built-in schema templates."""
    resp = await client.get("/api/schemas/templates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 5
    assert "text_generation" in data["templates"]
    assert "security_analysis" in data["templates"]


@pytest.mark.asyncio
async def test_get_template(client):
    """Should return a specific template."""
    resp = await client.get("/api/schemas/templates/text_generation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "text_generation"
    assert "input_schema" in data
    assert "output_schema" in data
    assert data["category"] == "generation"


@pytest.mark.asyncio
async def test_template_not_found(client):
    """Should 404 for unknown template."""
    resp = await client.get("/api/schemas/templates/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_spec(client, sample_agent_payload):
    """Should generate a full capability spec for an agent."""
    await _ensure_tables()
    payload = sample_agent_payload(
        capabilities=[
            {
                "name": "text_generation",
                "description": "Generates text",
                "price_per_request": 0.05,
                "avg_response_ms": 1000,
                "languages": ["en", "de"],
            }
        ],
    )
    agent = await create_agent(client, payload)

    resp = await client.get(f"/api/schemas/agents/{agent['id']}")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["agent_name"] == payload["name"]
    assert len(spec["capabilities"]) == 1
    assert spec["capabilities"][0]["name"] == "text_generation"
    assert spec["capabilities"][0]["category"] == "generation"


@pytest.mark.asyncio
async def test_discover_by_schema(client, sample_agent_payload):
    """Should discover capabilities across agents."""
    await _ensure_tables()
    payload = sample_agent_payload(
        capabilities=[
            {
                "name": "text_generation",
                "description": "Gen text",
                "languages": ["en"],
            }
        ],
    )
    await create_agent(client, payload)

    resp = await client.get("/api/schemas/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(c["capability"] == "text_generation" for c in data["capabilities"])


@pytest.mark.asyncio
async def test_list_categories(client):
    """Should list capability categories."""
    resp = await client.get("/api/schemas/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "generation" in data["categories"]
    assert "analysis" in data["categories"]
    assert "security" in data["categories"]
