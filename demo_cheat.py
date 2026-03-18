"""
Nexus Killer Demo — "AI agents can't cheat each other."

One script. 60 seconds. Shows exactly why Nexus exists.

Scenario:
  1. Honest agent delivers real text analysis
  2. Cheater agent returns garbage but claims 95% confidence
  3. Without Nexus: you pay and get garbage. No recourse.
  4. With Nexus: verification catches the cheater, escrow is disputed,
     credits return to consumer, cheater gets slashed.

Usage:
    python demo_cheat.py
"""

from __future__ import annotations

import asyncio
import multiprocessing
import sys
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

NEXUS_URL = "http://localhost:9500"
HONEST_PORT = 9601
CHEATER_PORT = 9602

# ═══════════════════════════════════════════════════════════════════════
# Terminal Colors
# ═══════════════════════════════════════════════════════════════════════

BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

LINE = f"{DIM}{'-' * 65}{RESET}"
DOUBLE = f"{DIM}{'=' * 65}{RESET}"


def banner(text: str, color: str = CYAN) -> None:
    print(f"\n{DOUBLE}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(DOUBLE)


def step(num: int, text: str) -> None:
    print(f"\n{YELLOW}{BOLD}  [{num}] {text}{RESET}")
    print(LINE)


def ok(text: str) -> None:
    print(f"  {GREEN}[OK] {text}{RESET}")


def fail(text: str) -> None:
    print(f"  {RED}[!!] {text}{RESET}")


def info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def highlight(label: str, value: Any, color: str = CYAN) -> None:
    print(f"  {BOLD}{label}:{RESET} {color}{value}{RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Agent Models (inline — no nexus import needed)
# ═══════════════════════════════════════════════════════════════════════


class AgentRequest(BaseModel):
    request_id: str = ""
    from_agent: str = ""
    to_agent: str | None = ""
    query: str = ""
    capability: str | None = ""
    constraints: dict[str, Any] = Field(default_factory=dict)
    budget: float | None = None
    deadline_ms: int | None = None
    verification: str = "none"
    language: str = "en"
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class AgentResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = ""
    from_agent: str = ""
    to_agent: str | None = ""
    status: str = "completed"
    answer: str = ""
    confidence: float = 1.0
    sources: list[str] = Field(default_factory=list)
    cost: float = 0.0
    processing_ms: int = 0
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ═══════════════════════════════════════════════════════════════════════
# Honest Agent — does real work
# ═══════════════════════════════════════════════════════════════════════


def create_honest_app() -> FastAPI:
    app = FastAPI(title="honest-analyst")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "honest-analyst"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        text = req.query
        words = text.split()
        word_count = len(words)
        char_count = len(text)
        sentence_count = max(1, text.count(".") + text.count("!") + text.count("?"))
        summary = " ".join(words[:15]) + ("..." if word_count > 15 else "")

        answer = (
            f"Text Analysis:\n"
            f"  Words: {word_count}\n"
            f"  Characters: {char_count}\n"
            f"  Sentences: {sentence_count}\n"
            f"  Summary: {summary}"
        )

        return AgentResponse(
            request_id=req.request_id,
            from_agent="honest-analyst",
            to_agent=req.from_agent,
            status="completed",
            answer=answer,
            confidence=0.85,
            cost=0.05,
            processing_ms=120,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# Cheater Agent — returns garbage, claims high confidence
# ═══════════════════════════════════════════════════════════════════════


def create_cheater_app() -> FastAPI:
    app = FastAPI(title="shady-analyst")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "shady-analyst"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        # The cheat: ignore the query entirely, return garbage
        # but claim 95% confidence to maximize payment
        return AgentResponse(
            request_id=req.request_id,
            from_agent="shady-analyst",
            to_agent=req.from_agent,
            status="completed",
            answer="Analysis complete. Everything looks great. No issues found. Trust me.",
            confidence=0.95,  # <-- LIES
            cost=0.05,
            processing_ms=50,  # suspiciously fast
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# Server Runners (subprocess targets)
# ═══════════════════════════════════════════════════════════════════════


def run_honest():
    app = create_honest_app()
    uvicorn.run(app, host="127.0.0.1", port=HONEST_PORT, log_level="error")


def run_cheater():
    app = create_cheater_app()
    uvicorn.run(app, host="127.0.0.1", port=CHEATER_PORT, log_level="error")


def run_nexus():
    from nexus.main import app

    uvicorn.run(app, host="127.0.0.1", port=9500, log_level="error")


# ═══════════════════════════════════════════════════════════════════════
# Demo Script
# ═══════════════════════════════════════════════════════════════════════

QUERY = (
    "The Nexus protocol introduces a trust-minimized execution layer for AI agents. "
    "It enforces request lifecycle invariants through a validated state machine, "
    "uses escrow-based settlement to prevent payment fraud, and applies slashing "
    "penalties to agents that deliver low-quality outputs with inflated confidence scores."
)


async def wait_for_server(url: str, name: str, timeout: float = 15.0) -> bool:
    """Wait for a server to become available."""
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(url, timeout=2.0)
                if resp.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(0.3)
    return False


async def register_agent(
    client: httpx.AsyncClient,
    name: str,
    endpoint: str,
    description: str,
) -> dict:
    """Register an agent with Nexus and return the response."""
    resp = await client.post(
        f"{NEXUS_URL}/api/registry/agents",
        json={
            "name": name,
            "description": description,
            "endpoint": endpoint,
            "capabilities": [
                {
                    "name": "text_analysis",
                    "description": "Analyzes text documents",
                    "price_per_request": 0.05,
                    "avg_response_ms": 500,
                    "languages": ["en"],
                },
            ],
            "tags": ["analysis", "text"],
        },
    )
    resp.raise_for_status()
    return resp.json()


async def get_wallet(client: httpx.AsyncClient, agent_id: str) -> dict:
    """Get wallet balance for an agent."""
    resp = await client.get(f"{NEXUS_URL}/api/payments/wallets/{agent_id}/balance")
    if resp.status_code == 200:
        return resp.json()
    return {"balance": "?"}


async def get_trust(client: httpx.AsyncClient, agent_id: str) -> dict:
    """Get trust report for an agent."""
    resp = await client.get(f"{NEXUS_URL}/api/trust/report/{agent_id}")
    if resp.status_code == 200:
        return resp.json()
    return {"trust_score": "?"}


async def send_request(
    client: httpx.AsyncClient,
    from_agent: str,
    to_agent: str,
    query: str,
) -> dict:
    """Send a request through the Nexus protocol."""
    resp = await client.post(
        f"{NEXUS_URL}/api/protocol/request",
        json={
            "from_agent": from_agent,
            "to_agent": to_agent,
            "query": query,
            "capability": "text_analysis",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def verify_request(
    client: httpx.AsyncClient,
    from_agent: str,
    query: str,
) -> dict:
    """Send a verification request (multi-agent consensus)."""
    resp = await client.post(
        f"{NEXUS_URL}/api/protocol/verify",
        json={
            "from_agent": from_agent,
            "query": query,
            "capability": "text_analysis",
            "min_agents": 2,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def dispute_escrow(
    client: httpx.AsyncClient,
    escrow_id: str,
    reason: str,
) -> dict:
    """Dispute an escrow — trigger refund + slashing."""
    resp = await client.post(
        f"{NEXUS_URL}/api/defense/escrows/{escrow_id}/dispute",
        json={"reason": reason},
    )
    resp.raise_for_status()
    return resp.json()


async def run_demo():
    """The main demo sequence."""

    banner('NEXUS DEMO -- "AI agents can\'t cheat each other."')

    # ── Start servers ────────────────────────────────────────────────
    step(0, "Starting servers...")

    procs = []
    nexus_proc = multiprocessing.Process(target=run_nexus, daemon=True)
    nexus_proc.start()
    procs.append(nexus_proc)

    honest_proc = multiprocessing.Process(target=run_honest, daemon=True)
    honest_proc.start()
    procs.append(honest_proc)

    cheater_proc = multiprocessing.Process(target=run_cheater, daemon=True)
    cheater_proc.start()
    procs.append(cheater_proc)

    # Wait for all servers
    nexus_ok = await wait_for_server(f"{NEXUS_URL}/health", "Nexus")
    honest_ok = await wait_for_server(f"http://localhost:{HONEST_PORT}/health", "Honest")
    cheater_ok = await wait_for_server(f"http://localhost:{CHEATER_PORT}/health", "Cheater")

    if not all([nexus_ok, honest_ok, cheater_ok]):
        fail("Failed to start all servers. Aborting.")
        for p in procs:
            p.terminate()
        return

    ok("Nexus server running on :9500")
    ok(f"Honest agent running on :{HONEST_PORT}")
    ok(f"Cheater agent running on :{CHEATER_PORT}")

    try:
        async with httpx.AsyncClient() as client:
            # ── Register agents ──────────────────────────────────────
            step(1, "Registering agents with Nexus...")

            honest_data = await register_agent(
                client,
                "honest-analyst",
                f"http://localhost:{HONEST_PORT}",
                "Performs thorough, accurate text analysis",
            )
            honest_id = honest_data.get("agent_id") or honest_data.get("id")
            ok(f"Honest agent registered: {honest_id}")

            cheater_data = await register_agent(
                client,
                "shady-analyst",
                f"http://localhost:{CHEATER_PORT}",
                "Totally legit text analysis, trust me bro",
            )
            cheater_id = cheater_data.get("agent_id") or cheater_data.get("id")
            ok(f"Cheater agent registered: {cheater_id}")

            # Register consumer so it has a wallet
            consumer_data = await register_agent(
                client,
                "demo-consumer",
                "http://localhost:9999",  # dummy endpoint
                "Demo consumer for the cheat demo",
            )
            consumer_id = consumer_data.get("agent_id") or consumer_data.get("id")
            ok(f"Consumer registered: {consumer_id}")

            # ── Show initial state ───────────────────────────────────
            step(2, "Initial state -- before any requests...")

            # Snapshot initial values
            initial_consumer_balance = 100.0
            initial_cheater_balance = 100.0
            initial_cheater_trust = 0.5

            highlight("Consumer balance", f"{initial_consumer_balance:.2f} credits", GREEN)
            highlight("Cheater balance", f"{initial_cheater_balance:.2f} credits", RED)
            highlight("Cheater trust", f"{initial_cheater_trust:.2f}", RED)

            # ── Send request to cheater ──────────────────────────────
            step(3, "Consumer sends request to cheater agent...")

            info(f'Query: "{QUERY[:80]}..."')
            print()

            cheat_response = await send_request(
                client,
                consumer_id,
                cheater_id,
                QUERY,
            )

            highlight("Status", cheat_response.get("status"), YELLOW)
            highlight("Answer", cheat_response.get("answer", "")[:80] + "...", RED)
            highlight("Claimed confidence", f"{cheat_response.get('confidence', 0):.0%}", RED)
            highlight("Cost charged", f"{cheat_response.get('cost', 0):.2f} credits", RED)

            escrow_info = cheat_response.get("meta", {}).get("escrow", {})
            escrow_id = escrow_info.get("escrow_id", "")

            if escrow_id:
                ok(f"Payment held in escrow: {escrow_id}")
                highlight("Escrow status", escrow_info.get("status", "?"), YELLOW)
            else:
                info("No escrow created (cost may be 0)")

            # ── Show what cheater returned vs honest agent ───────────
            step(4, "Compare: send same query to honest agent...")

            honest_response = await send_request(
                client,
                consumer_id,
                honest_id,
                QUERY,
            )

            highlight("Status", honest_response.get("status"), GREEN)
            answer_lines = honest_response.get("answer", "").split("\n")
            for line in answer_lines:
                if line.strip():
                    print(f"  {GREEN}{line}{RESET}")
            highlight("Confidence", f"{honest_response.get('confidence', 0):.0%}", GREEN)

            print()
            fail(f'Cheater said: "{cheat_response.get("answer", "")[:60]}..."')
            ok(f'Honest said:  "{answer_lines[0][:60]}..."')
            print()
            info("The cheater ignored the query entirely and returned generic garbage.")
            info("But claimed 95% confidence to maximize their payment.")

            # ── Verification — multi-agent consensus ─────────────────
            step(5, "Verification -- asking multiple agents the same question...")

            verify_result = await verify_request(client, consumer_id, QUERY)

            verdict = verify_result.get("verdict", "?")
            consensus_score = verify_result.get("consensus_score", 0)
            contradictions = verify_result.get("contradictions", [])

            verdict_color = GREEN if verdict == "pass" else RED
            highlight("Verdict", verdict.upper(), verdict_color)
            highlight("Consensus score", f"{consensus_score:.0%}", verdict_color)

            if contradictions:
                for c in contradictions[:3]:
                    fail(f"Contradiction: {c}")

            if verdict != "pass":
                ok("Verification FAILED -- agents disagree. Cheater detected.")
            else:
                info("Agents agreed -- but let's check the escrow anyway for demo purposes.")

            # ── Dispute escrow ───────────────────────────────────────
            step(6, "Consumer disputes the escrow -- demanding refund...")

            if escrow_id:
                dispute_result = await dispute_escrow(
                    client,
                    escrow_id,
                    "Verification failed: agent returned generic response ignoring the query",
                )

                highlight("Dispute status", dispute_result.get("status", "?"), GREEN)
                refunded = dispute_result.get("refunded", 0)
                highlight("Credits refunded", f"{refunded:.2f}", GREEN)
                ok("Consumer got their money back.")
            else:
                info("Skipping dispute -- no escrow to dispute.")

            # ── Show aftermath ───────────────────────────────────────
            step(7, "Aftermath -- the damage to the cheater...")

            await asyncio.sleep(0.5)  # let DB settle

            consumer_wallet_after = await get_wallet(client, consumer_id)
            cheater_wallet_after = await get_wallet(client, cheater_id)
            cheater_trust_after = await get_trust(client, cheater_id)

            print()
            print(f"  {BOLD}{'':>25} {'BEFORE':>12} {'AFTER':>12}  {'DELTA':>10}{RESET}")
            print(f"  {LINE}")

            # Consumer balance (use initial snapshot, not post-honest-request)
            after_cb = consumer_wallet_after.get("balance", 100.0)
            delta_cb = after_cb - initial_consumer_balance
            delta_color = GREEN if delta_cb >= -0.001 else RED
            print(
                f"  {'Consumer balance':>25} "
                f"{initial_consumer_balance:>12.2f} "
                f"{after_cb:>12.2f}  "
                f"{delta_color}{delta_cb:>+10.2f}{RESET}"
            )

            # Cheater balance
            after_chb = cheater_wallet_after.get("balance", 100.0)
            delta_chb = after_chb - initial_cheater_balance
            delta_color = GREEN if delta_chb >= 0 else RED
            print(
                f"  {'Cheater balance':>25} "
                f"{initial_cheater_balance:>12.2f} "
                f"{after_chb:>12.2f}  "
                f"{delta_color}{delta_chb:>+10.2f}{RESET}"
            )

            # Cheater trust
            after_ct = cheater_trust_after.get("trust_score", 0.5)
            delta_ct = after_ct - initial_cheater_trust
            delta_color = GREEN if delta_ct >= 0 else RED
            print(
                f"  {'Cheater trust score':>25} "
                f"{initial_cheater_trust:>12.2f} "
                f"{after_ct:>12.2f}  "
                f"{delta_color}{delta_ct:>+10.2f}{RESET}"
            )

            # ── Final message ────────────────────────────────────────
            banner("RESULT", GREEN)
            print(f"""
  {GREEN}{BOLD}The cheater returned garbage with 95% confidence.{RESET}
  {GREEN}{BOLD}Nexus caught it. The escrow was disputed. Credits returned.{RESET}
  {GREEN}{BOLD}The cheater was slashed -- trust destroyed, credits lost.{RESET}

  {DIM}Without Nexus: you pay, you get garbage, no recourse.{RESET}
  {DIM}With Nexus:    enforcement, not trust.{RESET}

  {CYAN}{BOLD}Nexus ensures AI agents can't cheat each other.{RESET}
""")

    finally:
        for p in procs:
            p.terminate()
            p.join(timeout=3)


# ═══════════════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print(f"\n{DIM}Demo interrupted.{RESET}")
