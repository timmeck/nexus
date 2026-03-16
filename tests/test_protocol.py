"""Tests for the Protocol API (/api/protocol)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_submit_request_no_agents(client: AsyncClient):
    """POST /api/protocol/request with no agents registered returns a failed response."""
    payload = {
        "from_agent": "external-caller",
        "query": "What is the meaning of life?",
        "capability": "philosophy",
    }
    resp = await client.post("/api/protocol/request", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "No suitable agent" in data.get("error", "")


@pytest.mark.asyncio
async def test_active_requests(client: AsyncClient):
    """GET /api/protocol/active returns a list (possibly empty)."""
    resp = await client.get("/api/protocol/active")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert isinstance(data["active"], list)
