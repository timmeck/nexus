"""Adversarial Defense — Slashing, Escrow, Challenges, Sybil Detection.

Protects the Nexus network from:
- Bad actors claiming high confidence then delivering garbage
- Payment fraud via immediate settlement
- Trust farming by Sybil swarms
- Colluding agents with suspiciously similar outputs
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from nexus.config import TRUST_PENALTY, TRUST_REWARD, MIN_TRUST, MAX_TRUST
from nexus.database import get_db, to_json, from_json

log = logging.getLogger("nexus.defense")

# ── Config ────────────────────────────────────────────────────────

ESCROW_WINDOW_SECONDS = 60          # How long payments are held
SLASH_BASE_PENALTY = 0.15           # Base trust slash for bad output
SLASH_CREDIT_MULTIPLIER = 2.0       # Credit penalty = cost * multiplier
CHALLENGE_FEE = 0.5                 # Cost to challenge an output
CHALLENGE_REWARD = 2.0              # Reward if challenge upheld
SYBIL_MIN_INTERACTIONS = 5          # Min interactions before earning trust
SYBIL_MAX_REGISTRATIONS_PER_HOUR = 10
SYBIL_SIMILARITY_THRESHOLD = 0.85   # Flag if responses this similar

DEFENSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS escrow (
    escrow_id    TEXT PRIMARY KEY,
    request_id   TEXT NOT NULL,
    consumer_id  TEXT NOT NULL,
    provider_id  TEXT NOT NULL,
    amount       REAL NOT NULL,
    status       TEXT DEFAULT 'held',
    created_at   TEXT NOT NULL,
    release_at   TEXT NOT NULL,
    resolved_at  TEXT
);

CREATE TABLE IF NOT EXISTS challenges (
    challenge_id  TEXT PRIMARY KEY,
    request_id    TEXT NOT NULL,
    challenger_id TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    reason        TEXT DEFAULT '',
    status        TEXT DEFAULT 'pending',
    ruling        TEXT DEFAULT '',
    fee_paid      REAL DEFAULT 0.0,
    reward_paid   REAL DEFAULT 0.0,
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS slashing_log (
    slash_id     TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    trust_before REAL,
    trust_after  REAL,
    credits_lost REAL DEFAULT 0.0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_escrow_status ON escrow(status);
CREATE INDEX IF NOT EXISTS idx_escrow_release ON escrow(release_at);
CREATE INDEX IF NOT EXISTS idx_challenges_status ON challenges(status);
CREATE INDEX IF NOT EXISTS idx_slashing_agent ON slashing_log(agent_id);
"""


async def ensure_tables():
    """Create defense tables."""
    db = await get_db()
    await db.executescript(DEFENSE_SCHEMA)
    await db.commit()


# ── Feature 7: Slashing Penalties ─────────────────────────────────


async def slash_agent(
    agent_id: str,
    request_id: str,
    reason: str,
    claimed_confidence: float = 0.0,
    actual_quality: float = 0.0,
) -> dict:
    """Slash an agent's trust and credits for bad output.

    Penalty scales with the gap between claimed confidence and actual quality.
    High confidence + bad output = severe punishment.
    """
    db = await get_db()

    # Get current trust
    row = await db.execute("SELECT trust_score FROM agents WHERE id = ?", (agent_id,))
    agent = await row.fetchone()
    if not agent:
        return {"error": "Agent not found"}

    trust_before = agent["trust_score"]

    # Calculate penalty proportional to confidence gap
    confidence_gap = max(0, claimed_confidence - actual_quality)
    trust_penalty = SLASH_BASE_PENALTY + (confidence_gap * 0.3)
    trust_after = max(MIN_TRUST, trust_before - trust_penalty)

    # Update trust
    await db.execute(
        "UPDATE agents SET trust_score = ? WHERE id = ?",
        (trust_after, agent_id),
    )

    # Credit penalty
    credits_lost = 0.0
    try:
        from nexus.payments.service import get_wallet
        wallet = await get_wallet(agent_id)
        if wallet and wallet["balance"] > 0:
            credits_lost = min(wallet["balance"], SLASH_CREDIT_MULTIPLIER * confidence_gap)
            if credits_lost > 0:
                await db.execute(
                    "UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE agent_id = ?",
                    (credits_lost, datetime.utcnow().isoformat(), agent_id),
                )
    except Exception:
        pass

    # Log the slash
    slash_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO slashing_log (slash_id, agent_id, request_id, reason, trust_before, trust_after, credits_lost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (slash_id, agent_id, request_id, reason, trust_before, trust_after, credits_lost, now),
    )

    await db.commit()
    log.warning(
        "SLASHED agent %s: trust %.2f -> %.2f, credits lost: %.4f (%s)",
        agent_id, trust_before, trust_after, credits_lost, reason,
    )

    return {
        "slash_id": slash_id,
        "agent_id": agent_id,
        "trust_before": round(trust_before, 4),
        "trust_after": round(trust_after, 4),
        "credits_lost": round(credits_lost, 4),
        "reason": reason,
    }


async def get_slashing_history(agent_id: str | None = None, limit: int = 50) -> list[dict]:
    """Get slashing log, optionally filtered by agent."""
    db = await get_db()
    if agent_id:
        rows = await db.execute(
            "SELECT * FROM slashing_log WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM slashing_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in await rows.fetchall()]


# ── Feature 8: Escrow / Delayed Settlement ────────────────────────


async def create_escrow(
    request_id: str,
    consumer_id: str,
    provider_id: str,
    amount: float,
) -> dict:
    """Hold payment in escrow instead of immediate settlement."""
    db = await get_db()
    escrow_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow()
    release_at = now + timedelta(seconds=ESCROW_WINDOW_SECONDS)

    # Debit consumer immediately
    await db.execute(
        "UPDATE wallets SET balance = balance - ?, total_spent = total_spent + ?, updated_at = ? WHERE agent_id = ?",
        (amount, amount, now.isoformat(), consumer_id),
    )

    await db.execute(
        "INSERT INTO escrow (escrow_id, request_id, consumer_id, provider_id, amount, status, created_at, release_at) VALUES (?, ?, ?, ?, ?, 'held', ?, ?)",
        (escrow_id, request_id, consumer_id, provider_id, amount, now.isoformat(), release_at.isoformat()),
    )
    await db.commit()

    log.info("Escrow %s: %.4f credits held for %ds (request %s)",
             escrow_id, amount, ESCROW_WINDOW_SECONDS, request_id[:8])

    return {
        "escrow_id": escrow_id,
        "amount": amount,
        "status": "held",
        "release_at": release_at.isoformat(),
    }


async def release_escrow(escrow_id: str) -> dict:
    """Release escrowed funds to the provider."""
    db = await get_db()
    row = await db.execute("SELECT * FROM escrow WHERE escrow_id = ? AND status = 'held'", (escrow_id,))
    escrow = await row.fetchone()
    if not escrow:
        return {"error": "Escrow not found or already resolved"}

    now = datetime.utcnow().isoformat()

    # Credit provider
    await db.execute(
        "UPDATE wallets SET balance = balance + ?, total_earned = total_earned + ?, updated_at = ? WHERE agent_id = ?",
        (escrow["amount"], escrow["amount"], now, escrow["provider_id"]),
    )

    # Record transaction
    tx_id = uuid.uuid4().hex[:12]
    await db.execute(
        "INSERT INTO transactions (tx_id, request_id, from_agent, to_agent, amount, tx_type, description, balance_after, created_at) VALUES (?, ?, ?, ?, ?, 'escrow_release', 'Escrow released', 0, ?)",
        (tx_id, escrow["request_id"], escrow["consumer_id"], escrow["provider_id"], escrow["amount"], now),
    )

    await db.execute(
        "UPDATE escrow SET status = 'released', resolved_at = ? WHERE escrow_id = ?",
        (now, escrow_id),
    )
    await db.commit()

    log.info("Escrow %s released: %.4f credits to %s", escrow_id, escrow["amount"], escrow["provider_id"])
    return {"escrow_id": escrow_id, "status": "released", "amount": escrow["amount"]}


async def dispute_escrow(escrow_id: str, reason: str = "") -> dict:
    """Consumer disputes escrow — funds returned to consumer."""
    db = await get_db()
    row = await db.execute("SELECT * FROM escrow WHERE escrow_id = ? AND status = 'held'", (escrow_id,))
    escrow = await row.fetchone()
    if not escrow:
        return {"error": "Escrow not found or already resolved"}

    now = datetime.utcnow().isoformat()

    # Refund consumer
    await db.execute(
        "UPDATE wallets SET balance = balance + ?, total_spent = total_spent - ?, updated_at = ? WHERE agent_id = ?",
        (escrow["amount"], escrow["amount"], now, escrow["consumer_id"]),
    )

    await db.execute(
        "UPDATE escrow SET status = 'disputed', resolved_at = ? WHERE escrow_id = ?",
        (now, escrow_id),
    )
    await db.commit()

    # Slash the provider
    await slash_agent(
        escrow["provider_id"], escrow["request_id"],
        reason=f"Escrow disputed: {reason}",
    )

    log.warning("Escrow %s disputed: %.4f refunded to %s", escrow_id, escrow["amount"], escrow["consumer_id"])
    return {"escrow_id": escrow_id, "status": "disputed", "refunded": escrow["amount"]}


async def release_mature_escrows() -> int:
    """Release all escrows past their settlement window. Call periodically."""
    db = await get_db()
    now = datetime.utcnow().isoformat()
    rows = await db.execute(
        "SELECT escrow_id FROM escrow WHERE status = 'held' AND release_at <= ?",
        (now,),
    )
    released = 0
    for row in await rows.fetchall():
        await release_escrow(row["escrow_id"])
        released += 1
    return released


async def list_escrows(status: str | None = None, limit: int = 50) -> list[dict]:
    """List escrow records."""
    db = await get_db()
    if status:
        rows = await db.execute(
            "SELECT * FROM escrow WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM escrow ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in await rows.fetchall()]


# ── Feature 9: Challenge Mechanism ────────────────────────────────


async def create_challenge(
    request_id: str,
    challenger_id: str,
    target_id: str,
    reason: str = "",
) -> dict:
    """Challenge another agent's output. Challenger pays a fee."""
    db = await get_db()

    # Charge challenger the fee
    try:
        from nexus.payments.service import get_balance
        balance = await get_balance(challenger_id)
        if balance < CHALLENGE_FEE:
            return {"error": f"Insufficient balance for challenge fee ({CHALLENGE_FEE} credits)"}

        await db.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE agent_id = ?",
            (CHALLENGE_FEE, datetime.utcnow().isoformat(), challenger_id),
        )
    except Exception:
        pass

    challenge_id = uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()

    await db.execute(
        "INSERT INTO challenges (challenge_id, request_id, challenger_id, target_id, reason, status, fee_paid, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (challenge_id, request_id, challenger_id, target_id, reason, CHALLENGE_FEE, now),
    )
    await db.commit()

    log.info("Challenge %s: %s challenges %s (request %s)",
             challenge_id, challenger_id, target_id, request_id[:8])

    return {
        "challenge_id": challenge_id,
        "status": "pending",
        "fee_paid": CHALLENGE_FEE,
    }


async def resolve_challenge(challenge_id: str, upheld: bool, ruling: str = "") -> dict:
    """Resolve a challenge. If upheld, challenger is rewarded and target is slashed."""
    db = await get_db()
    row = await db.execute("SELECT * FROM challenges WHERE challenge_id = ? AND status = 'pending'", (challenge_id,))
    challenge = await row.fetchone()
    if not challenge:
        return {"error": "Challenge not found or already resolved"}

    now = datetime.utcnow().isoformat()
    reward_paid = 0.0

    if upheld:
        # Slash the target
        await slash_agent(
            challenge["target_id"], challenge["request_id"],
            reason=f"Challenge upheld: {ruling}",
        )

        # Reward the challenger
        reward_paid = CHALLENGE_REWARD
        try:
            await db.execute(
                "UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE agent_id = ?",
                (reward_paid, now, challenge["challenger_id"]),
            )
        except Exception:
            pass

        status = "upheld"
    else:
        # Challenge rejected — fee is kept by the network (burned)
        status = "rejected"

    await db.execute(
        "UPDATE challenges SET status = ?, ruling = ?, reward_paid = ?, resolved_at = ? WHERE challenge_id = ?",
        (status, ruling, reward_paid, now, challenge_id),
    )
    await db.commit()

    log.info("Challenge %s %s: %s", challenge_id, status, ruling)
    return {
        "challenge_id": challenge_id,
        "status": status,
        "upheld": upheld,
        "reward_paid": reward_paid,
        "ruling": ruling,
    }


async def list_challenges(status: str | None = None, limit: int = 50) -> list[dict]:
    """List challenges."""
    db = await get_db()
    if status:
        rows = await db.execute(
            "SELECT * FROM challenges WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = await db.execute(
            "SELECT * FROM challenges ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in await rows.fetchall()]


# ── Feature 10: Sybil Detection ──────────────────────────────────


async def check_registration_rate() -> dict:
    """Check if registration rate exceeds threshold (Sybil indicator)."""
    db = await get_db()
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    row = await db.execute(
        "SELECT COUNT(*) as c FROM agents WHERE registered_at >= ?",
        (one_hour_ago,),
    )
    count = (await row.fetchone())["c"]
    exceeded = count >= SYBIL_MAX_REGISTRATIONS_PER_HOUR

    return {
        "registrations_last_hour": count,
        "limit": SYBIL_MAX_REGISTRATIONS_PER_HOUR,
        "rate_exceeded": exceeded,
    }


async def check_agent_maturity(agent_id: str) -> dict:
    """Check if an agent has enough history to be trusted."""
    db = await get_db()
    row = await db.execute(
        "SELECT total_interactions, trust_score, registered_at FROM agents WHERE id = ?",
        (agent_id,),
    )
    agent = await row.fetchone()
    if not agent:
        return {"error": "Agent not found"}

    mature = agent["total_interactions"] >= SYBIL_MIN_INTERACTIONS
    age_hours = (datetime.utcnow() - datetime.fromisoformat(agent["registered_at"])).total_seconds() / 3600

    return {
        "agent_id": agent_id,
        "interactions": agent["total_interactions"],
        "min_required": SYBIL_MIN_INTERACTIONS,
        "mature": mature,
        "age_hours": round(age_hours, 1),
        "trust_score": agent["trust_score"],
    }


async def detect_sybil_clusters() -> list[dict]:
    """Detect agents with suspiciously similar capabilities (potential Sybils).

    Flags groups of agents that:
    - Registered around the same time
    - Have identical or near-identical capabilities
    - Have similar trust scores despite being new
    """
    db = await get_db()
    rows = await db.execute(
        "SELECT id, name, capabilities, tags, registered_at, trust_score, total_interactions FROM agents ORDER BY registered_at DESC",
    )
    agents = [dict(r) for r in await rows.fetchall()]

    clusters = []
    checked = set()

    for i, a in enumerate(agents):
        if a["id"] in checked:
            continue
        cluster = [a]
        a_caps = a["capabilities"] if isinstance(a["capabilities"], str) else to_json(a["capabilities"])

        for j in range(i + 1, len(agents)):
            b = agents[j]
            if b["id"] in checked:
                continue
            b_caps = b["capabilities"] if isinstance(b["capabilities"], str) else to_json(b["capabilities"])

            # Check capability similarity
            sim = SequenceMatcher(None, a_caps, b_caps).ratio()
            if sim >= SYBIL_SIMILARITY_THRESHOLD:
                cluster.append(b)
                checked.add(b["id"])

        if len(cluster) >= 2:
            checked.add(a["id"])
            clusters.append({
                "agents": [{"id": x["id"], "name": x["name"], "interactions": x["total_interactions"]} for x in cluster],
                "count": len(cluster),
                "similarity": "high",
                "risk": "medium" if len(cluster) < 4 else "high",
            })

    return clusters


async def get_defense_stats() -> dict:
    """Get aggregate defense statistics."""
    db = await get_db()

    slashes = await db.execute("SELECT COUNT(*) as c FROM slashing_log")
    s = (await slashes.fetchone())["c"]

    escrows_held = await db.execute("SELECT COUNT(*) as c FROM escrow WHERE status = 'held'")
    eh = (await escrows_held.fetchone())["c"]

    escrows_total = await db.execute("SELECT COUNT(*) as c FROM escrow")
    et = (await escrows_total.fetchone())["c"]

    challenges_total = await db.execute("SELECT COUNT(*) as c FROM challenges")
    ct = (await challenges_total.fetchone())["c"]

    challenges_upheld = await db.execute("SELECT COUNT(*) as c FROM challenges WHERE status = 'upheld'")
    cu = (await challenges_upheld.fetchone())["c"]

    return {
        "total_slashes": s,
        "escrows_held": eh,
        "escrows_total": et,
        "challenges_total": ct,
        "challenges_upheld": cu,
    }
