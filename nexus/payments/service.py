"""Micropayments — Credit system for agent-to-agent transactions.

Each agent has a wallet with a credit balance.
- Consumers pay per request
- Providers earn per response
- Budget limits enforced before routing
- Full transaction history
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from nexus.database import get_db

log = logging.getLogger("nexus.payments")

# Default starting balance for new agents
DEFAULT_BALANCE = 100.0

PAYMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    agent_id    TEXT PRIMARY KEY,
    agent_name  TEXT NOT NULL,
    balance     REAL DEFAULT 100.0,
    total_spent REAL DEFAULT 0.0,
    total_earned REAL DEFAULT 0.0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id        TEXT PRIMARY KEY,
    request_id   TEXT NOT NULL,
    from_agent   TEXT NOT NULL,
    to_agent     TEXT NOT NULL,
    amount       REAL NOT NULL,
    tx_type      TEXT NOT NULL,
    description  TEXT DEFAULT '',
    balance_after REAL DEFAULT 0.0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_from ON transactions(from_agent);
CREATE INDEX IF NOT EXISTS idx_tx_to ON transactions(to_agent);
CREATE INDEX IF NOT EXISTS idx_tx_request ON transactions(request_id);
"""


async def ensure_tables():
    """Create payment tables."""
    db = await get_db()
    await db.executescript(PAYMENTS_SCHEMA)
    await db.commit()


# ── Wallet Management ────────────────────────────────────────────


async def get_or_create_wallet(agent_id: str, agent_name: str = "") -> dict:
    """Get wallet for an agent, creating it if it doesn't exist."""
    db = await get_db()
    row = await db.execute("SELECT * FROM wallets WHERE agent_id = ?", (agent_id,))
    wallet = await row.fetchone()

    if wallet:
        return dict(wallet)

    now = datetime.utcnow().isoformat()
    await db.execute(
        "INSERT INTO wallets (agent_id, agent_name, balance, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (agent_id, agent_name, DEFAULT_BALANCE, now, now),
    )
    await db.commit()
    log.info("Created wallet for %s (%s) with %.2f credits", agent_name, agent_id, DEFAULT_BALANCE)

    row = await db.execute("SELECT * FROM wallets WHERE agent_id = ?", (agent_id,))
    return dict(await row.fetchone())


async def get_wallet(agent_id: str) -> dict | None:
    """Get wallet for an agent."""
    db = await get_db()
    row = await db.execute("SELECT * FROM wallets WHERE agent_id = ?", (agent_id,))
    wallet = await row.fetchone()
    return dict(wallet) if wallet else None


async def get_balance(agent_id: str) -> float:
    """Get current balance for an agent."""
    wallet = await get_wallet(agent_id)
    return wallet["balance"] if wallet else 0.0


async def check_budget(agent_id: str, amount: float) -> bool:
    """Check if an agent can afford a transaction."""
    balance = await get_balance(agent_id)
    return balance >= amount


async def add_credits(agent_id: str, amount: float, reason: str = "top-up") -> dict:
    """Add credits to an agent's wallet."""
    db = await get_db()
    now = datetime.utcnow().isoformat()

    wallet = await get_or_create_wallet(agent_id)
    new_balance = wallet["balance"] + amount

    await db.execute(
        "UPDATE wallets SET balance = ?, updated_at = ? WHERE agent_id = ?",
        (new_balance, now, agent_id),
    )
    await db.commit()

    log.info("Added %.4f credits to %s (new balance: %.4f)", amount, agent_id, new_balance)
    return {"agent_id": agent_id, "added": amount, "balance": new_balance}


# ── Transactions ─────────────────────────────────────────────────


async def process_payment(
    request_id: str,
    consumer_id: str,
    provider_id: str,
    amount: float,
    description: str = "",
) -> dict:
    """Process a payment from consumer to provider.

    Returns {"success": bool, "tx_id": str, ...}
    """
    db = await get_db()
    now = datetime.utcnow().isoformat()

    # Get or create wallets
    consumer_wallet = await get_or_create_wallet(consumer_id)
    provider_wallet = await get_or_create_wallet(provider_id)

    # Check balance
    if consumer_wallet["balance"] < amount:
        return {
            "success": False,
            "error": f"Insufficient balance: {consumer_wallet['balance']:.4f} < {amount:.4f}",
            "balance": consumer_wallet["balance"],
        }

    # Debit consumer
    consumer_new = consumer_wallet["balance"] - amount
    await db.execute(
        "UPDATE wallets SET balance = ?, total_spent = total_spent + ?, updated_at = ? WHERE agent_id = ?",
        (consumer_new, amount, now, consumer_id),
    )

    # Credit provider
    provider_new = provider_wallet["balance"] + amount
    await db.execute(
        "UPDATE wallets SET balance = ?, total_earned = total_earned + ?, updated_at = ? WHERE agent_id = ?",
        (provider_new, amount, now, provider_id),
    )

    # Record transactions
    tx_id = uuid.uuid4().hex[:12]
    await db.execute(
        "INSERT INTO transactions (tx_id, request_id, from_agent, to_agent, amount, tx_type, description, balance_after, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id, request_id, consumer_id, provider_id, amount, "payment", description, consumer_new, now),
    )

    tx_id_earn = uuid.uuid4().hex[:12]
    await db.execute(
        "INSERT INTO transactions (tx_id, request_id, from_agent, to_agent, amount, tx_type, description, balance_after, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id_earn, request_id, consumer_id, provider_id, amount, "earning", description, provider_new, now),
    )

    await db.commit()

    log.info(
        "Payment: %s -> %s  %.4f credits (request %s)",
        consumer_id,
        provider_id,
        amount,
        request_id[:8],
    )

    return {
        "success": True,
        "tx_id": tx_id,
        "amount": amount,
        "consumer_balance": consumer_new,
        "provider_balance": provider_new,
    }


async def get_transaction_history(agent_id: str, limit: int = 50) -> list[dict]:
    """Get transaction history for an agent."""
    db = await get_db()
    rows = await db.execute(
        """SELECT * FROM transactions
           WHERE from_agent = ? OR to_agent = ?
           ORDER BY created_at DESC LIMIT ?""",
        (agent_id, agent_id, limit),
    )
    return [dict(r) for r in await rows.fetchall()]


async def get_all_wallets() -> list[dict]:
    """Get all wallets sorted by balance."""
    db = await get_db()
    rows = await db.execute("SELECT * FROM wallets ORDER BY balance DESC")
    return [dict(r) for r in await rows.fetchall()]


async def get_payment_stats() -> dict:
    """Get aggregate payment statistics."""
    db = await get_db()

    wallets = await db.execute("SELECT COUNT(*) as c, COALESCE(SUM(balance), 0) as total FROM wallets")
    w = await wallets.fetchone()

    txs = await db.execute(
        "SELECT COUNT(*) as c, COALESCE(SUM(amount), 0) as vol FROM transactions WHERE tx_type = 'payment'"
    )
    t = await txs.fetchone()

    return {
        "wallets": w["c"],
        "total_credits_in_circulation": round(w["total"], 4),
        "total_transactions": t["c"],
        "total_volume": round(t["vol"], 4),
    }
