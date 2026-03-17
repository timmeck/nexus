"""Enterprise Policy Layer — Data locality, compliance claims, gateway config.

Enables enterprise-grade controls:
- Route only to agents in a specific jurisdiction (GDPR, HIPAA)
- Agents declare compliance claims with cryptographic attestation
- Audit trail for regulated industries
- Edge gateway integration config
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime

from nexus.database import from_json, get_db, to_json

log = logging.getLogger("nexus.policy")

POLICY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_locality (
    agent_id     TEXT PRIMARY KEY,
    region       TEXT NOT NULL DEFAULT 'global',
    jurisdiction TEXT NOT NULL DEFAULT 'none',
    datacenter   TEXT DEFAULT '',
    country_code TEXT DEFAULT '',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_claims (
    claim_id     TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    claim_type   TEXT NOT NULL,
    claim_value  TEXT NOT NULL,
    description  TEXT DEFAULT '',
    attestation  TEXT DEFAULT '',
    verified     INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    expires_at   TEXT
);

CREATE TABLE IF NOT EXISTS routing_policies (
    policy_id    TEXT PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    description  TEXT DEFAULT '',
    rules        TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER DEFAULT 1,
    priority     INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    agent_id     TEXT,
    request_id   TEXT,
    policy_id    TEXT,
    details      TEXT DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gateway_configs (
    config_id    TEXT PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    gateway_type TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    settings     TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_locality_region ON agent_locality(region);
CREATE INDEX IF NOT EXISTS idx_compliance_agent ON compliance_claims(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
"""


async def ensure_tables():
    """Create policy tables."""
    db = await get_db()
    await db.executescript(POLICY_SCHEMA)
    await db.commit()


# ── Feature 11: Data Locality ─────────────────────────────────────


async def set_agent_locality(
    agent_id: str,
    region: str,
    jurisdiction: str = "none",
    datacenter: str = "",
    country_code: str = "",
) -> dict:
    """Set geographic/jurisdiction info for an agent."""
    db = await get_db()
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT OR REPLACE INTO agent_locality
           (agent_id, region, jurisdiction, datacenter, country_code, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_id, region, jurisdiction, datacenter, country_code, now),
    )
    await db.commit()

    await _audit(
        "locality_set",
        agent_id=agent_id,
        details={
            "region": region,
            "jurisdiction": jurisdiction,
        },
    )

    return {
        "agent_id": agent_id,
        "region": region,
        "jurisdiction": jurisdiction,
        "datacenter": datacenter,
        "country_code": country_code,
    }


async def get_agent_locality(agent_id: str) -> dict | None:
    """Get locality info for an agent."""
    db = await get_db()
    row = await db.execute("SELECT * FROM agent_locality WHERE agent_id = ?", (agent_id,))
    loc = await row.fetchone()
    return dict(loc) if loc else None


async def filter_agents_by_locality(
    agent_ids: list[str],
    required_region: str | None = None,
    required_jurisdiction: str | None = None,
    required_country: str | None = None,
) -> list[str]:
    """Filter agents by locality requirements. Returns IDs that match."""
    if not required_region and not required_jurisdiction and not required_country:
        return agent_ids

    db = await get_db()
    placeholders = ",".join("?" * len(agent_ids))
    conditions = [f"agent_id IN ({placeholders})"]
    params = list(agent_ids)

    if required_region:
        conditions.append("(region = ? OR region = 'global')")
        params.append(required_region)
    if required_jurisdiction:
        conditions.append("jurisdiction = ?")
        params.append(required_jurisdiction)
    if required_country:
        conditions.append("country_code = ?")
        params.append(required_country)

    query = f"SELECT agent_id FROM agent_locality WHERE {' AND '.join(conditions)}"
    rows = await db.execute(query, params)
    return [r["agent_id"] for r in await rows.fetchall()]


async def list_localities() -> list[dict]:
    """List all agent localities."""
    db = await get_db()
    rows = await db.execute("SELECT * FROM agent_locality ORDER BY region")
    return [dict(r) for r in await rows.fetchall()]


# ── Feature 12: Compliance Claims ─────────────────────────────────

CLAIM_TYPES = [
    "no_training_on_prompts",
    "data_deleted_after_response",
    "gdpr_compliant",
    "hipaa_compliant",
    "soc2_compliant",
    "iso27001",
    "data_encrypted_at_rest",
    "data_encrypted_in_transit",
    "no_third_party_sharing",
    "audit_logging_enabled",
]


async def add_compliance_claim(
    agent_id: str,
    claim_type: str,
    claim_value: str = "true",
    description: str = "",
    expires_at: str | None = None,
) -> dict:
    """Agent declares a compliance claim with attestation hash."""
    db = await get_db()
    claim_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    # Generate attestation hash (agent_id + claim + timestamp)
    attestation_data = f"{agent_id}:{claim_type}:{claim_value}:{now}"
    attestation = hashlib.sha256(attestation_data.encode()).hexdigest()

    await db.execute(
        """INSERT INTO compliance_claims
           (claim_id, agent_id, claim_type, claim_value, description, attestation, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (claim_id, agent_id, claim_type, claim_value, description, attestation, now, expires_at),
    )
    await db.commit()

    await _audit(
        "compliance_claim_added",
        agent_id=agent_id,
        details={
            "claim_id": claim_id,
            "claim_type": claim_type,
            "attestation": attestation[:16],
        },
    )

    return {
        "claim_id": claim_id,
        "agent_id": agent_id,
        "claim_type": claim_type,
        "attestation": attestation,
    }


async def get_agent_claims(agent_id: str) -> list[dict]:
    """Get all compliance claims for an agent."""
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM compliance_claims WHERE agent_id = ? ORDER BY created_at DESC",
        (agent_id,),
    )
    return [dict(r) for r in await rows.fetchall()]


async def verify_claim(claim_id: str) -> dict:
    """Mark a compliance claim as verified."""
    db = await get_db()
    row = await db.execute("SELECT * FROM compliance_claims WHERE claim_id = ?", (claim_id,))
    claim = await row.fetchone()
    if not claim:
        return {"error": "Claim not found"}

    await db.execute(
        "UPDATE compliance_claims SET verified = 1 WHERE claim_id = ?",
        (claim_id,),
    )
    await db.commit()

    await _audit(
        "compliance_claim_verified",
        agent_id=claim["agent_id"],
        details={
            "claim_id": claim_id,
            "claim_type": claim["claim_type"],
        },
    )

    return {"claim_id": claim_id, "verified": True}


async def filter_agents_by_compliance(
    agent_ids: list[str],
    required_claims: list[str],
) -> list[str]:
    """Filter agents that have all required compliance claims."""
    if not required_claims:
        return agent_ids

    db = await get_db()
    matching = set(agent_ids)

    for claim_type in required_claims:
        placeholders = ",".join("?" * len(list(matching)))
        if not matching:
            return []
        rows = await db.execute(
            f"SELECT DISTINCT agent_id FROM compliance_claims WHERE agent_id IN ({placeholders}) AND claim_type = ?",
            (*list(matching), claim_type),
        )
        agents_with_claim = {r["agent_id"] for r in await rows.fetchall()}
        matching = matching & agents_with_claim

    return list(matching)


# ── Routing Policies ──────────────────────────────────────────────


async def create_routing_policy(
    name: str,
    rules: dict,
    description: str = "",
    priority: int = 0,
) -> dict:
    """Create a routing policy.

    Rules format:
    {
        "require_region": "eu",
        "require_jurisdiction": "gdpr",
        "require_compliance": ["no_training_on_prompts", "data_deleted_after_response"],
        "require_country": "DE",
        "max_price": 0.1,
        "min_trust": 0.7,
    }
    """
    db = await get_db()
    policy_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO routing_policies
           (policy_id, name, description, rules, enabled, priority, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
        (policy_id, name, description, to_json(rules), priority, now, now),
    )
    await db.commit()

    await _audit("policy_created", details={"policy_id": policy_id, "name": name})

    return {"policy_id": policy_id, "name": name, "rules": rules}


async def list_policies(enabled_only: bool = False) -> list[dict]:
    """List routing policies."""
    db = await get_db()
    query = "SELECT * FROM routing_policies"
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY priority DESC"
    rows = await db.execute(query)
    results = []
    for r in await rows.fetchall():
        d = dict(r)
        d["rules"] = from_json(d["rules"]) if isinstance(d["rules"], str) else d["rules"]
        results.append(d)
    return results


async def get_policy(policy_id: str) -> dict | None:
    """Get a specific policy."""
    db = await get_db()
    row = await db.execute("SELECT * FROM routing_policies WHERE policy_id = ?", (policy_id,))
    p = await row.fetchone()
    if not p:
        return None
    d = dict(p)
    d["rules"] = from_json(d["rules"]) if isinstance(d["rules"], str) else d["rules"]
    return d


async def toggle_policy(policy_id: str) -> dict:
    """Enable/disable a policy."""
    db = await get_db()
    now = datetime.utcnow().isoformat()
    await db.execute(
        "UPDATE routing_policies SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END, updated_at = ? WHERE policy_id = ?",
        (now, policy_id),
    )
    await db.commit()
    return await get_policy(policy_id) or {"error": "Policy not found"}


async def delete_policy(policy_id: str) -> bool:
    """Delete a routing policy."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM routing_policies WHERE policy_id = ?", (policy_id,))
    await db.commit()
    return cursor.rowcount > 0


async def apply_policies(agent_ids: list[str]) -> list[str]:
    """Apply all enabled routing policies to filter agent list."""
    policies = await list_policies(enabled_only=True)
    remaining = list(agent_ids)

    for policy in policies:
        rules = policy["rules"]
        if not remaining:
            break

        if rules.get("require_region") or rules.get("require_jurisdiction") or rules.get("require_country"):
            remaining = await filter_agents_by_locality(
                remaining,
                required_region=rules.get("require_region"),
                required_jurisdiction=rules.get("require_jurisdiction"),
                required_country=rules.get("require_country"),
            )

        if rules.get("require_compliance"):
            remaining = await filter_agents_by_compliance(
                remaining,
                required_claims=rules["require_compliance"],
            )

    return remaining


# ── Feature 13: Edge Gateway Config ───────────────────────────────


async def add_gateway(
    name: str,
    gateway_type: str,
    endpoint: str,
    settings: dict | None = None,
) -> dict:
    """Register an edge gateway (Kong, Tyk, DreamFactory, etc.)."""
    db = await get_db()
    config_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    await db.execute(
        """INSERT INTO gateway_configs
           (config_id, name, gateway_type, endpoint, settings, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (config_id, name, gateway_type, endpoint, to_json(settings or {}), now, now),
    )
    await db.commit()

    await _audit(
        "gateway_added",
        details={
            "config_id": config_id,
            "name": name,
            "type": gateway_type,
        },
    )

    return {"config_id": config_id, "name": name, "gateway_type": gateway_type, "endpoint": endpoint}


async def list_gateways() -> list[dict]:
    """List all gateway configurations."""
    db = await get_db()
    rows = await db.execute("SELECT * FROM gateway_configs ORDER BY name")
    results = []
    for r in await rows.fetchall():
        d = dict(r)
        d["settings"] = from_json(d["settings"]) if isinstance(d["settings"], str) else d["settings"]
        results.append(d)
    return results


async def delete_gateway(config_id: str) -> bool:
    """Remove a gateway configuration."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM gateway_configs WHERE config_id = ?", (config_id,))
    await db.commit()
    return cursor.rowcount > 0


# ── Audit Trail ───────────────────────────────────────────────────


async def _audit(
    event_type: str,
    agent_id: str | None = None,
    request_id: str | None = None,
    policy_id: str | None = None,
    details: dict | None = None,
):
    """Record an audit event."""
    db = await get_db()
    audit_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO audit_log (audit_id, event_type, agent_id, request_id, policy_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (audit_id, event_type, agent_id, request_id, policy_id, to_json(details or {}), now),
    )
    await db.commit()


async def get_audit_log(
    event_type: str | None = None,
    agent_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query audit log."""
    db = await get_db()
    conditions = []
    params = []

    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)

    query = "SELECT * FROM audit_log"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = await db.execute(query, params)
    results = []
    for r in await rows.fetchall():
        d = dict(r)
        d["details"] = from_json(d["details"]) if isinstance(d["details"], str) else d["details"]
        results.append(d)
    return results


async def get_policy_stats() -> dict:
    """Get policy layer statistics."""
    db = await get_db()

    localities = await db.execute("SELECT COUNT(*) as c FROM agent_locality")
    loc_count = (await localities.fetchone())["c"]

    claims = await db.execute("SELECT COUNT(*) as c FROM compliance_claims")
    claims_count = (await claims.fetchone())["c"]

    verified = await db.execute("SELECT COUNT(*) as c FROM compliance_claims WHERE verified = 1")
    verified_count = (await verified.fetchone())["c"]

    policies = await db.execute("SELECT COUNT(*) as c FROM routing_policies WHERE enabled = 1")
    policies_count = (await policies.fetchone())["c"]

    gateways = await db.execute("SELECT COUNT(*) as c FROM gateway_configs WHERE enabled = 1")
    gateways_count = (await gateways.fetchone())["c"]

    audits = await db.execute("SELECT COUNT(*) as c FROM audit_log")
    audits_count = (await audits.fetchone())["c"]

    return {
        "agents_with_locality": loc_count,
        "compliance_claims": claims_count,
        "verified_claims": verified_count,
        "active_policies": policies_count,
        "active_gateways": gateways_count,
        "audit_events": audits_count,
    }
