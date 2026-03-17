"""SQLite database layer with aiosqlite."""

from __future__ import annotations

import json
import logging

import aiosqlite

from nexus.config import DATA_DIR, DB_PATH

log = logging.getLogger("nexus.db")

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    description   TEXT DEFAULT '',
    endpoint      TEXT NOT NULL,
    capabilities  TEXT DEFAULT '[]',
    tags          TEXT DEFAULT '[]',
    meta          TEXT DEFAULT 'null',
    trust_score   REAL DEFAULT 0.5,
    status        TEXT DEFAULT 'online',
    registered_at TEXT NOT NULL,
    last_heartbeat TEXT,
    total_interactions    INTEGER DEFAULT 0,
    successful_interactions INTEGER DEFAULT 0,
    api_key       TEXT,
    auth_enabled  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id TEXT PRIMARY KEY,
    request_id     TEXT NOT NULL,
    consumer_id    TEXT NOT NULL,
    provider_id    TEXT NOT NULL,
    success        INTEGER DEFAULT 0,
    confidence     REAL DEFAULT 0.0,
    verified       INTEGER DEFAULT 0,
    cost           REAL DEFAULT 0.0,
    response_ms    INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interactions_provider ON interactions(provider_id);
CREATE INDEX IF NOT EXISTS idx_interactions_consumer ON interactions(consumer_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    query           TEXT NOT NULL,
    capability      TEXT NOT NULL,
    agents_queried  INTEGER DEFAULT 0,
    agents_responded INTEGER DEFAULT 0,
    consensus       INTEGER DEFAULT 0,
    consensus_score REAL DEFAULT 0.0,
    best_answer     TEXT DEFAULT '',
    contradictions  TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS request_events (
    event_id     TEXT PRIMARY KEY,
    request_id   TEXT NOT NULL,
    step         TEXT NOT NULL,
    from_state   TEXT DEFAULT '',
    to_state     TEXT DEFAULT '',
    actor        TEXT DEFAULT 'system',
    details      TEXT DEFAULT '{}',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_events_request ON request_events(request_id);
"""


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.executescript(SCHEMA)
        await _db.commit()
        log.info("Database initialized at %s", DB_PATH)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def to_json(obj: object) -> str:
    """Serialize to JSON string for storage."""
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), default=str)
    return json.dumps(obj, default=str)


def from_json(text: str | None) -> object:
    """Deserialize JSON string from storage."""
    if text is None:
        return None
    return json.loads(text)
