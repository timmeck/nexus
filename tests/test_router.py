"""Tests for the Router API (/api/router)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import create_agent

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_route_no_agents(client: AsyncClient):
    """POST /api/router/route with no agents returns empty candidates."""
    payload = {
        "from_agent": "caller",
        "query": "Hello",
        "capability": "nonexistent_cap",
    }
    resp = await client.post("/api/router/route", json=payload, params={"strategy": "best"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "best"
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_route_best_strategy(client: AsyncClient, sample_agent_payload):
    """POST /api/router/route with 'best' strategy returns ranked candidates."""
    await create_agent(
        client,
        sample_agent_payload(
            name="fast-agent",
            capabilities=[
                {
                    "name": "summarize",
                    "description": "Text summarization",
                    "price_per_request": 0.5,
                    "avg_response_ms": 1000,
                }
            ],
        ),
    )
    await create_agent(
        client,
        sample_agent_payload(
            name="slow-agent",
            capabilities=[
                {
                    "name": "summarize",
                    "description": "Text summarization",
                    "price_per_request": 0.1,
                    "avg_response_ms": 10000,
                }
            ],
        ),
    )

    payload = {
        "from_agent": "caller",
        "query": "Summarize this text",
        "capability": "summarize",
    }
    resp = await client.post("/api/router/route", json=payload, params={"strategy": "best"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "best"
    assert len(data["candidates"]) == 2
    # Both agents should be present
    names = {c["agent_name"] for c in data["candidates"]}
    assert names == {"fast-agent", "slow-agent"}
    # First candidate should have a higher score
    assert data["candidates"][0]["score"] >= data["candidates"][1]["score"]


@pytest.mark.asyncio
async def test_route_cheapest(client: AsyncClient, sample_agent_payload):
    """POST /api/router/route with 'cheapest' strategy prefers lower price."""
    await create_agent(
        client,
        sample_agent_payload(
            name="expensive",
            capabilities=[
                {
                    "name": "translate",
                    "description": "Translation",
                    "price_per_request": 5.0,
                    "avg_response_ms": 2000,
                }
            ],
        ),
    )
    await create_agent(
        client,
        sample_agent_payload(
            name="budget",
            capabilities=[
                {
                    "name": "translate",
                    "description": "Translation",
                    "price_per_request": 0.1,
                    "avg_response_ms": 2000,
                }
            ],
        ),
    )

    payload = {
        "from_agent": "caller",
        "query": "Translate this",
        "capability": "translate",
    }
    resp = await client.post("/api/router/route", json=payload, params={"strategy": "cheapest"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "cheapest"
    assert len(data["candidates"]) == 2
    # The cheaper agent should rank first
    assert data["candidates"][0]["agent_name"] == "budget"
