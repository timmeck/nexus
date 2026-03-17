"""Tests for Enterprise Policy Layer — Locality, Compliance, Gateways, Audit."""

from __future__ import annotations

import pytest
from tests.conftest import create_agent


async def _ensure_all():
    from nexus.federation.service import ensure_tables; await ensure_tables()
    from nexus.payments.service import ensure_tables as pt; await pt()
    from nexus.defense.service import ensure_tables as dt; await dt()
    from nexus.policy.service import ensure_tables as pol; await pol()


# ── Data Locality ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_locality(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    resp = await client.post("/api/policy/locality", json={
        "agent_id": agent["id"],
        "region": "eu",
        "jurisdiction": "gdpr",
        "country_code": "DE",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["region"] == "eu"
    assert data["jurisdiction"] == "gdpr"


@pytest.mark.asyncio
async def test_get_locality(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    await client.post("/api/policy/locality", json={
        "agent_id": agent["id"], "region": "us", "jurisdiction": "hipaa",
    })
    resp = await client.get(f"/api/policy/locality/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["region"] == "us"


@pytest.mark.asyncio
async def test_list_localities(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    await client.post("/api/policy/locality", json={
        "agent_id": agent["id"], "region": "eu",
    })
    resp = await client.get("/api/policy/localities")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


# ── Compliance Claims ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_compliance_claim(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    resp = await client.post("/api/policy/compliance", json={
        "agent_id": agent["id"],
        "claim_type": "no_training_on_prompts",
        "description": "We never train on user prompts",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "attestation" in data
    assert len(data["attestation"]) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_get_agent_claims(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    await client.post("/api/policy/compliance", json={
        "agent_id": agent["id"], "claim_type": "gdpr_compliant",
    })
    resp = await client.get(f"/api/policy/compliance/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


@pytest.mark.asyncio
async def test_verify_claim(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    claim_resp = await client.post("/api/policy/compliance", json={
        "agent_id": agent["id"], "claim_type": "soc2_compliant",
    })
    claim_id = claim_resp.json()["claim_id"]
    resp = await client.post(f"/api/policy/compliance/{claim_id}/verify")
    assert resp.status_code == 200
    assert resp.json()["verified"] is True


@pytest.mark.asyncio
async def test_list_claim_types(client):
    resp = await client.get("/api/policy/compliance/types")
    assert resp.status_code == 200
    types = resp.json()["claim_types"]
    assert "gdpr_compliant" in types
    assert "no_training_on_prompts" in types


# ── Routing Policies ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_routing_policy(client):
    await _ensure_all()
    resp = await client.post("/api/policy/routing", json={
        "name": "eu-only-gdpr",
        "description": "Only route to GDPR-compliant EU agents",
        "rules": {
            "require_region": "eu",
            "require_jurisdiction": "gdpr",
            "require_compliance": ["no_training_on_prompts"],
        },
        "priority": 10,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "eu-only-gdpr"


@pytest.mark.asyncio
async def test_list_policies(client):
    await _ensure_all()
    await client.post("/api/policy/routing", json={
        "name": "test-policy-list",
        "rules": {"min_trust": 0.5},
    })
    resp = await client.get("/api/policy/routing")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


@pytest.mark.asyncio
async def test_toggle_policy(client):
    await _ensure_all()
    create = await client.post("/api/policy/routing", json={
        "name": "toggle-test",
        "rules": {},
    })
    pid = create.json()["policy_id"]
    resp = await client.post(f"/api/policy/routing/{pid}/toggle")
    assert resp.status_code == 200
    assert resp.json()["enabled"] == 0  # Was 1, now 0


# ── Edge Gateways ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_gateway(client):
    await _ensure_all()
    resp = await client.post("/api/policy/gateways", json={
        "name": "kong-edge",
        "gateway_type": "kong",
        "endpoint": "http://kong:8000",
        "settings": {"rate_limit": 100},
    })
    assert resp.status_code == 200
    assert resp.json()["gateway_type"] == "kong"


@pytest.mark.asyncio
async def test_list_gateways(client):
    await _ensure_all()
    await client.post("/api/policy/gateways", json={
        "name": "tyk-gw", "gateway_type": "tyk", "endpoint": "http://tyk:8080",
    })
    resp = await client.get("/api/policy/gateways")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


# ── Audit Trail ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log(client, sample_agent_payload):
    await _ensure_all()
    agent = await create_agent(client, sample_agent_payload())
    await client.post("/api/policy/locality", json={
        "agent_id": agent["id"], "region": "eu",
    })
    resp = await client.get("/api/policy/audit")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


# ── Stats ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_policy_stats(client):
    await _ensure_all()
    resp = await client.get("/api/policy/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents_with_locality" in data
    assert "compliance_claims" in data
    assert "active_policies" in data
    assert "active_gateways" in data
    assert "audit_events" in data
