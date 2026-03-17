"""Payments API — Micropayment endpoints for the credit system."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from nexus.payments import service as payments

router = APIRouter(prefix="/api/payments", tags=["payments"])


class TopUpRequest(BaseModel):
    agent_id: str
    amount: float = Field(..., gt=0, le=10000)
    reason: str = "manual top-up"


# ── Wallets ──────────────────────────────────────────────────────


@router.get("/wallets")
async def list_wallets():
    """List all agent wallets."""
    wallets = await payments.get_all_wallets()
    return {"wallets": wallets, "count": len(wallets)}


@router.get("/wallets/{agent_id}")
async def get_wallet(agent_id: str):
    """Get wallet for a specific agent."""
    wallet = await payments.get_wallet(agent_id)
    if not wallet:
        raise HTTPException(404, "Wallet not found")
    return wallet


@router.post("/wallets/{agent_id}/topup")
async def top_up(agent_id: str, body: TopUpRequest):
    """Add credits to an agent's wallet."""
    return await payments.add_credits(agent_id, body.amount, body.reason)


@router.get("/wallets/{agent_id}/balance")
async def get_balance(agent_id: str):
    """Get current balance for an agent."""
    balance = await payments.get_balance(agent_id)
    return {"agent_id": agent_id, "balance": balance}


# ── Transactions ─────────────────────────────────────────────────


@router.get("/transactions/{agent_id}")
async def transaction_history(agent_id: str, limit: int = 50):
    """Get transaction history for an agent."""
    txs = await payments.get_transaction_history(agent_id, limit=limit)
    return {"transactions": txs, "count": len(txs)}


# ── Stats ────────────────────────────────────────────────────────


@router.get("/stats")
async def payment_stats():
    """Get aggregate payment statistics."""
    return await payments.get_payment_stats()
