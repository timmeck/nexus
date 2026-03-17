"""Agent Registry — Discovery Layer.

Handles agent registration, lookup, capability queries, and heartbeat tracking.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from nexus.auth import generate_api_key
from nexus.database import get_db, to_json, from_json
from nexus.models.agent import Agent, AgentCreate, AgentStatus, AgentUpdate, Capability

log = logging.getLogger("nexus.registry")


async def register_agent(payload: AgentCreate) -> Agent:
    """Register a new agent in the network."""
    db = await get_db()
    agent_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    # Check for duplicate name
    row = await db.execute("SELECT id FROM agents WHERE name = ?", (payload.name,))
    existing = await row.fetchone()
    if existing:
        raise ValueError(f"Agent with name '{payload.name}' already registered")

    caps_json = to_json([c.model_dump() for c in payload.capabilities])
    tags_json = to_json(payload.tags)
    meta_json = to_json(payload.meta)
    api_key = generate_api_key()

    await db.execute(
        """INSERT INTO agents (id, name, description, endpoint, capabilities, tags, meta,
                               trust_score, status, registered_at, last_heartbeat,
                               api_key, auth_enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0.5, 'online', ?, ?, ?, 1)""",
        (agent_id, payload.name, payload.description, payload.endpoint,
         caps_json, tags_json, meta_json, now, now, api_key),
    )
    await db.commit()
    log.info("Registered agent %s (%s) at %s [auth=enabled]", payload.name, agent_id, payload.endpoint)

    # Auto-create wallet for the new agent
    try:
        from nexus.payments.service import get_or_create_wallet
        await get_or_create_wallet(agent_id, payload.name)
    except Exception as e:
        log.warning("Could not create wallet for %s: %s", agent_id, e)

    return await get_agent(agent_id)


async def get_agent(agent_id: str) -> Agent | None:
    """Get an agent by ID."""
    db = await get_db()
    row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
    record = await row.fetchone()
    if not record:
        return None
    return _row_to_agent(record)


async def get_agent_by_name(name: str) -> Agent | None:
    """Get an agent by name."""
    db = await get_db()
    row = await db.execute("SELECT * FROM agents WHERE name = ?", (name,))
    record = await row.fetchone()
    if not record:
        return None
    return _row_to_agent(record)


async def list_agents(
    status: AgentStatus | None = None,
    capability: str | None = None,
    tag: str | None = None,
) -> list[Agent]:
    """List agents with optional filters."""
    db = await get_db()
    query = "SELECT * FROM agents"
    conditions: list[str] = []
    params: list[str] = []

    if status:
        conditions.append("status = ?")
        params.append(status.value)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY trust_score DESC"

    rows = await db.execute(query, params)
    agents = [_row_to_agent(r) for r in await rows.fetchall()]

    # Post-filter by capability (JSON field, easier in Python)
    if capability:
        agents = [
            a for a in agents
            if any(c.name.lower() == capability.lower() for c in a.capabilities)
        ]

    # Post-filter by tag
    if tag:
        agents = [a for a in agents if tag.lower() in [t.lower() for t in a.tags]]

    return agents


async def update_agent(agent_id: str, payload: AgentUpdate) -> Agent | None:
    """Update an existing agent."""
    db = await get_db()
    agent = await get_agent(agent_id)
    if not agent:
        return None

    updates: list[str] = []
    params: list = []

    if payload.description is not None:
        updates.append("description = ?")
        params.append(payload.description)
    if payload.endpoint is not None:
        updates.append("endpoint = ?")
        params.append(payload.endpoint)
    if payload.capabilities is not None:
        updates.append("capabilities = ?")
        params.append(to_json([c.model_dump() for c in payload.capabilities]))
    if payload.tags is not None:
        updates.append("tags = ?")
        params.append(to_json(payload.tags))
    if payload.meta is not None:
        updates.append("meta = ?")
        params.append(to_json(payload.meta))
    if payload.status is not None:
        updates.append("status = ?")
        params.append(payload.status.value)

    if not updates:
        return agent

    params.append(agent_id)
    await db.execute(
        f"UPDATE agents SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    await db.commit()
    return await get_agent(agent_id)


async def delete_agent(agent_id: str) -> bool:
    """Unregister an agent."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()
    deleted = cursor.rowcount > 0
    if deleted:
        log.info("Deleted agent %s", agent_id)
    return deleted


async def heartbeat(agent_id: str) -> bool:
    """Update agent heartbeat timestamp."""
    db = await get_db()
    now = datetime.utcnow().isoformat()
    cursor = await db.execute(
        "UPDATE agents SET last_heartbeat = ?, status = 'online' WHERE id = ?",
        (now, agent_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def find_by_capability(
    capability: str,
    language: str | None = None,
    min_trust: float = 0.0,
) -> list[Agent]:
    """Find agents that offer a specific capability."""
    agents = await list_agents(status=AgentStatus.ONLINE, capability=capability)
    if min_trust > 0:
        agents = [a for a in agents if a.trust_score >= min_trust]
    if language:
        agents = [
            a for a in agents
            if any(
                language.lower() in [l.lower() for l in c.languages]
                for c in a.capabilities
                if c.name.lower() == capability.lower()
            )
        ]
    return agents


def _row_to_agent(row) -> Agent:
    """Convert a database row to an Agent model."""
    return Agent(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        endpoint=row["endpoint"],
        capabilities=[Capability(**c) for c in from_json(row["capabilities"])],
        tags=from_json(row["tags"]),
        meta=from_json(row["meta"]),
        trust_score=row["trust_score"],
        status=AgentStatus(row["status"]),
        registered_at=datetime.fromisoformat(row["registered_at"]),
        last_heartbeat=datetime.fromisoformat(row["last_heartbeat"]) if row["last_heartbeat"] else None,
        total_interactions=row["total_interactions"],
        successful_interactions=row["successful_interactions"],
        api_key=row["api_key"] if "api_key" in row.keys() else None,
        auth_enabled=bool(row["auth_enabled"]) if "auth_enabled" in row.keys() else False,
    )
