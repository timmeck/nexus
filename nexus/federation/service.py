"""Federation — Connect multiple Nexus instances into a network.

Like email servers: each Nexus instance has its own agents,
but can discover and route requests to agents on other instances.

Concepts:
- Peer: another Nexus instance
- Sync: exchange agent registries with peers
- Remote Agent: an agent registered on a peer, accessible through federation
- Forwarding: routing a request to a peer that has the right agent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from nexus.database import get_db, to_json, from_json
from nexus.models.agent import Agent, Capability, AgentStatus

log = logging.getLogger("nexus.federation")


FEDERATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS peers (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    endpoint TEXT NOT NULL,
    status TEXT DEFAULT 'unknown',
    agent_count INTEGER DEFAULT 0,
    last_sync_at TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remote_agents (
    id TEXT PRIMARY KEY,
    peer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    capabilities TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    trust_score REAL DEFAULT 0.5,
    endpoint TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    FOREIGN KEY (peer_id) REFERENCES peers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_remote_peer ON remote_agents(peer_id);
"""


async def ensure_tables():
    """Create federation tables."""
    db = await get_db()
    await db.executescript(FEDERATION_SCHEMA)
    await db.commit()


# ── Peer Management ────────────────────────────────────────────────

async def add_peer(name: str, endpoint: str) -> dict:
    """Add a peer Nexus instance."""
    import uuid
    db = await get_db()
    peer_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    # Check duplicate
    row = await db.execute("SELECT id FROM peers WHERE endpoint = ?", (endpoint,))
    existing = await row.fetchone()
    if existing:
        return {"id": existing["id"], "name": name, "status": "already_exists"}

    await db.execute(
        "INSERT INTO peers (id, name, endpoint, status, registered_at) VALUES (?, ?, ?, 'unknown', ?)",
        (peer_id, name, endpoint.rstrip("/"), now))
    await db.commit()
    log.info("Added peer: %s at %s", name, endpoint)
    return {"id": peer_id, "name": name, "endpoint": endpoint}


async def list_peers() -> list[dict]:
    db = await get_db()
    rows = await db.execute("SELECT * FROM peers ORDER BY name")
    return [dict(r) for r in await rows.fetchall()]


async def remove_peer(peer_id: str) -> bool:
    db = await get_db()
    await db.execute("DELETE FROM remote_agents WHERE peer_id = ?", (peer_id,))
    cursor = await db.execute("DELETE FROM peers WHERE id = ?", (peer_id,))
    await db.commit()
    return cursor.rowcount > 0


# ── Sync ───────────────────────────────────────────────────────────

async def sync_peer(peer_id: str) -> dict:
    """Sync agent registry with a peer. Pull their agents into remote_agents."""
    db = await get_db()
    row = await db.execute("SELECT * FROM peers WHERE id = ?", (peer_id,))
    peer = await row.fetchone()
    if not peer:
        return {"error": "Peer not found"}

    endpoint = peer["endpoint"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{endpoint}/api/registry/agents")
            resp.raise_for_status()
            data = resp.json()
            agents = data if isinstance(data, list) else data.get("agents", [])

        # Clear old remote agents for this peer
        await db.execute("DELETE FROM remote_agents WHERE peer_id = ?", (peer_id,))

        now = datetime.utcnow().isoformat()
        count = 0
        for agent in agents:
            agent_id = f"{peer_id}_{agent.get('id', agent.get('name', 'unknown'))}"
            caps = agent.get("capabilities", [])
            tags = agent.get("tags", [])

            await db.execute(
                "INSERT OR REPLACE INTO remote_agents (id, peer_id, name, description, capabilities, tags, trust_score, endpoint, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_id, peer_id, agent.get("name", ""),
                 agent.get("description", ""),
                 to_json(caps) if isinstance(caps, list) else caps,
                 to_json(tags) if isinstance(tags, list) else tags,
                 agent.get("trust_score", 0.5),
                 agent.get("endpoint", endpoint),
                 now))
            count += 1

        # Update peer status
        await db.execute(
            "UPDATE peers SET status = 'online', agent_count = ?, last_sync_at = ? WHERE id = ?",
            (count, now, peer_id))
        await db.commit()

        log.info("Synced %d agents from peer %s (%s)", count, peer["name"], endpoint)
        return {"peer": peer["name"], "agents_synced": count, "status": "online"}

    except Exception as e:
        await db.execute("UPDATE peers SET status = 'offline' WHERE id = ?", (peer_id,))
        await db.commit()
        log.error("Failed to sync peer %s: %s", peer["name"], e)
        return {"peer": peer["name"], "error": str(e), "status": "offline"}


async def sync_all_peers() -> list[dict]:
    """Sync with all registered peers."""
    peers = await list_peers()
    results = []
    for peer in peers:
        result = await sync_peer(peer["id"])
        results.append(result)
    return results


# ── Discovery (federated) ─────────────────────────────────────────

async def search_remote_agents(capability: str = None, tag: str = None) -> list[dict]:
    """Search agents across all peers."""
    db = await get_db()
    rows = await db.execute("SELECT ra.*, p.name as peer_name, p.endpoint as peer_endpoint FROM remote_agents ra JOIN peers p ON ra.peer_id = p.id ORDER BY ra.trust_score DESC")
    agents = [dict(r) for r in await rows.fetchall()]

    # Parse JSON fields
    for a in agents:
        if isinstance(a.get("capabilities"), str):
            a["capabilities"] = from_json(a["capabilities"])
        if isinstance(a.get("tags"), str):
            a["tags"] = from_json(a["tags"])

    # Filter by capability
    if capability:
        agents = [a for a in agents if any(
            (c.get("name", "") if isinstance(c, dict) else "").lower() == capability.lower()
            for c in (a.get("capabilities") or [])
        )]

    # Filter by tag
    if tag:
        agents = [a for a in agents if tag.lower() in [t.lower() for t in (a.get("tags") or [])]]

    return agents


async def forward_request(peer_endpoint: str, request_data: dict) -> dict:
    """Forward a Nexus request to a peer instance."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{peer_endpoint}/api/protocol/request", json=request_data)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": f"Forward failed: {e}", "status": "failed"}


# ── Federation Info ────────────────────────────────────────────────

async def get_federation_stats() -> dict:
    db = await get_db()
    peers = await db.execute("SELECT COUNT(*) as c FROM peers")
    remote = await db.execute("SELECT COUNT(*) as c FROM remote_agents")
    online = await db.execute("SELECT COUNT(*) as c FROM peers WHERE status = 'online'")
    return {
        "peers": (await peers.fetchone())["c"],
        "remote_agents": (await remote.fetchone())["c"],
        "peers_online": (await online.fetchone())["c"],
    }
