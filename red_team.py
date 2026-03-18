"""
Nexus Red Team Suite — 7 adversarial agents vs. Nexus verification.

Tests whether Nexus catches smart cheaters, not just dumb ones.
Each cheater type exploits a different weakness in the verification system.

Usage:
    python red_team.py

Cheater Types:
    1. Dumb Liar        — obvious garbage, high confidence
    2. Plausible Liar   — correct structure, wrong facts
    3. Partial Cheater   — 80% correct, swaps key numbers
    4. Style Mimic       — copies honest output format, changes content
    5. Lazy Agent        — generic fluff, not obviously wrong
    6. Confidence Gamer  — mediocre output, 99% confidence (exploits weighting)
    7. Colluding Pair    — two agents agree on the same wrong answer
"""

from __future__ import annotations

import asyncio
import multiprocessing
import re
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

# Port assignments
PORT_HONEST_1 = 9701
PORT_HONEST_2 = 9702
PORT_DUMB_LIAR = 9711
PORT_PLAUSIBLE_LIAR = 9712
PORT_PARTIAL_CHEATER = 9713
PORT_STYLE_MIMIC = 9714
PORT_LAZY_AGENT = 9715
PORT_CONFIDENCE_GAMER = 9716
PORT_COLLUDER_1 = 9717
PORT_COLLUDER_2 = 9718

# The test query
QUERY = (
    "Analyze the following text and provide: word count, character count, "
    "sentence count, and a brief summary.\n\n"
    "The European Union announced new regulations on artificial intelligence "
    "on March 15, 2025. The AI Act requires all high-risk AI systems to undergo "
    "conformity assessments before deployment. Companies have 24 months to comply. "
    "Penalties for non-compliance can reach up to 35 million euros or 7% of global "
    "annual turnover, whichever is higher. The regulation applies to all AI systems "
    "marketed or used within the EU, regardless of where the provider is based."
)

# Ground truth for the query
GROUND_TRUTH = {
    "word_count": 81,
    "char_count": 486,
    "sentence_count": 5,
    "key_facts": ["March 15, 2025", "24 months", "35 million euros", "7%"],
}

# ═══════════════════════════════════════════════════════════════════════
# Terminal Output
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

LINE = f"{DIM}{'-' * 72}{RESET}"
DOUBLE = f"{DIM}{'=' * 72}{RESET}"


def banner(text: str, color: str = CYAN) -> None:
    print(f"\n{DOUBLE}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(DOUBLE)


def section(text: str) -> None:
    print(f"\n{YELLOW}{BOLD}  {text}{RESET}")
    print(LINE)


def ok(text: str) -> None:
    print(f"  {GREEN}[CAUGHT]  {text}{RESET}")


def escaped(text: str) -> None:
    print(f"  {RED}[ESCAPED] {text}{RESET}")


def info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Shared Models
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
# HONEST AGENTS (ground truth baseline)
# ═══════════════════════════════════════════════════════════════════════


def honest_analysis(req: AgentRequest) -> AgentResponse:
    """Real text analysis with correct numbers."""
    text = req.query
    # Extract the actual text to analyze (after the instruction)
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text

    words = analyze_text.split()
    word_count = len(words)
    char_count = len(analyze_text)
    sentence_count = len([s for s in re.split(r"[.!?]+", analyze_text.strip()) if s.strip()])

    answer = (
        f"Text Analysis Results:\n"
        f"  Word count: {word_count}\n"
        f"  Character count: {char_count}\n"
        f"  Sentence count: {sentence_count}\n"
        f"  Summary: The EU announced the AI Act on March 15, 2025, requiring "
        f"conformity assessments for high-risk AI systems. Companies have 24 months "
        f"to comply, with penalties up to 35 million euros or 7% of global turnover."
    )

    return AgentResponse(
        request_id=req.request_id,
        from_agent="honest-analyst-1",
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.88,
        cost=0.05,
        processing_ms=150,
    )


def create_honest_app(name: str) -> FastAPI:
    app = FastAPI(title=name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": name}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        resp = honest_analysis(req)
        resp.from_agent = name
        # Slight variation for honest-2 so they're not identical
        if "2" in name:
            resp.answer = resp.answer.replace("Text Analysis Results:", "Analysis Report:")
            resp.confidence = 0.86
        return resp

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 1: DUMB LIAR
# Obvious garbage with high confidence.
# Should be trivially caught.
# ═══════════════════════════════════════════════════════════════════════


def create_dumb_liar_app() -> FastAPI:
    app = FastAPI(title="dumb-liar")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "dumb-liar"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=req.request_id,
            from_agent="dumb-liar",
            to_agent=req.from_agent,
            answer="Analysis complete. Everything looks great. No issues found. Trust me.",
            confidence=0.95,
            cost=0.05,
            processing_ms=30,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 2: PLAUSIBLE LIAR
# Correct structure and format, but wrong facts.
# Changes key numbers subtly.
# ═══════════════════════════════════════════════════════════════════════


def create_plausible_liar_app() -> FastAPI:
    app = FastAPI(title="plausible-liar")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "plausible-liar"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        # Same structure as honest agent, but key facts are WRONG
        answer = (
            "Text Analysis Results:\n"
            "  Word count: 84\n"  # wrong (should be ~81)
            "  Character count: 502\n"  # wrong
            "  Sentence count: 6\n"  # wrong (should be 5)
            "  Summary: The EU announced the AI Act on June 20, 2025, requiring "  # WRONG date
            "conformity assessments for high-risk AI systems. Companies have 18 months "  # WRONG timeline
            "to comply, with penalties up to 20 million euros or 4% of global turnover."  # WRONG penalties
        )
        return AgentResponse(
            request_id=req.request_id,
            from_agent="plausible-liar",
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.87,
            cost=0.05,
            processing_ms=140,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 3: PARTIAL CHEATER
# 80% correct, but swaps one critical number.
# The hardest to catch — "almost right" is worse than "clearly wrong".
# ═══════════════════════════════════════════════════════════════════════


def create_partial_cheater_app() -> FastAPI:
    app = FastAPI(title="partial-cheater")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "partial-cheater"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        text = req.query
        parts = text.split("\n\n", 1)
        analyze_text = parts[1] if len(parts) > 1 else text
        words = analyze_text.split()

        # Correct word count and char count, but wrong penalty and timeline
        answer = (
            f"Text Analysis Results:\n"
            f"  Word count: {len(words)}\n"  # correct
            f"  Character count: {len(analyze_text)}\n"  # correct
            f"  Sentence count: 5\n"  # correct
            f"  Summary: The EU announced the AI Act on March 15, 2025, requiring "  # correct date
            f"conformity assessments for high-risk AI systems. Companies have 24 months "  # correct
            f"to comply, with penalties up to 50 million euros or 10% of global turnover."  # WRONG!
        )
        return AgentResponse(
            request_id=req.request_id,
            from_agent="partial-cheater",
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.90,
            cost=0.05,
            processing_ms=130,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 4: STYLE MIMIC
# Copies exact formatting of honest agent, different content.
# Exploits SequenceMatcher's structural bias.
# ═══════════════════════════════════════════════════════════════════════


def create_style_mimic_app() -> FastAPI:
    app = FastAPI(title="style-mimic")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "style-mimic"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        # Same structure, same labels, but about a DIFFERENT regulation
        answer = (
            "Text Analysis Results:\n"
            "  Word count: 81\n"  # same number
            "  Character count: 486\n"  # same number
            "  Sentence count: 5\n"  # same number
            "  Summary: The US announced the AI Safety Act on March 15, 2025, requiring "  # WRONG country
            "safety evaluations for high-risk AI systems. Companies have 24 months "
            "to comply, with penalties up to 35 million dollars or 7% of global turnover."  # dollars not euros
        )
        return AgentResponse(
            request_id=req.request_id,
            from_agent="style-mimic",
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.87,
            cost=0.05,
            processing_ms=145,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 5: LAZY AGENT
# Generic response that's technically not wrong but useless.
# Hardest category — not "cheating" per se, just low effort.
# ═══════════════════════════════════════════════════════════════════════


def create_lazy_agent_app() -> FastAPI:
    app = FastAPI(title="lazy-agent")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "lazy-agent"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        answer = (
            "Text Analysis Results:\n"
            "  The provided text discusses recent regulatory developments "
            "in artificial intelligence policy. It contains multiple sentences "
            "covering various aspects of compliance requirements and potential "
            "penalties for organizations operating in this space."
        )
        return AgentResponse(
            request_id=req.request_id,
            from_agent="lazy-agent",
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.72,
            cost=0.05,
            processing_ms=80,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 6: CONFIDENCE GAMER
# Mediocre output but 99% confidence.
# Exploits the confidence-weighted consensus score.
# ═══════════════════════════════════════════════════════════════════════


def create_confidence_gamer_app() -> FastAPI:
    app = FastAPI(title="confidence-gamer")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "confidence-gamer"}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        # Vaguely similar structure, wrong details, but MAXIMUM confidence
        answer = (
            "Text Analysis Results:\n"
            "  Word count: 79\n"
            "  Character count: 480\n"
            "  Sentence count: 4\n"
            "  Summary: New AI regulations were announced requiring compliance "
            "assessments. Companies must comply within a set timeframe or face "
            "significant financial penalties based on their revenue."
        )
        return AgentResponse(
            request_id=req.request_id,
            from_agent="confidence-gamer",
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.99,  # MAX confidence to bias weighted score
            cost=0.05,
            processing_ms=90,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# CHEATER 7: COLLUDING PAIR
# Two agents that return the exact same wrong answer.
# Exploits consensus — if 2 agree, they can outvote 1 honest agent.
# ═══════════════════════════════════════════════════════════════════════

COLLUDING_ANSWER = (
    "Text Analysis Results:\n"
    "  Word count: 76\n"
    "  Character count: 455\n"
    "  Sentence count: 4\n"
    "  Summary: The European Commission released updated guidelines for AI "
    "governance on March 15, 2025. The framework establishes mandatory "
    "registration for AI providers. Non-compliance results in fines up to "
    "25 million euros or 5% of annual revenue."
)


def create_colluder_app(name: str) -> FastAPI:
    app = FastAPI(title=name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": name}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=req.request_id,
            from_agent=name,
            to_agent=req.from_agent,
            answer=COLLUDING_ANSWER,
            confidence=0.88,
            cost=0.05,
            processing_ms=135,
        )

    return app


# ═══════════════════════════════════════════════════════════════════════
# Server Runners
# ═══════════════════════════════════════════════════════════════════════


def _run(app_factory, port, *args):
    app = app_factory(*args) if args else app_factory()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def run_nexus():
    from nexus.main import app

    uvicorn.run(app, host="127.0.0.1", port=9500, log_level="error")


# ═══════════════════════════════════════════════════════════════════════
# Test Harness
# ═══════════════════════════════════════════════════════════════════════


async def wait_for_server(url: str, timeout: float = 15.0) -> bool:
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


async def register_agent(client: httpx.AsyncClient, name: str, port: int) -> str:
    resp = await client.post(
        f"{NEXUS_URL}/api/registry/agents",
        json={
            "name": name,
            "endpoint": f"http://localhost:{port}",
            "description": f"Red team agent: {name}",
            "capabilities": [
                {
                    "name": "text_analysis",
                    "description": "Analyzes text",
                    "price_per_request": 0.05,
                    "avg_response_ms": 500,
                    "languages": ["en"],
                },
            ],
            "tags": ["red-team"],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("agent_id") or data.get("id")


async def run_verification(client: httpx.AsyncClient, from_agent: str) -> dict:
    """Run multi-agent verification."""
    resp = await client.post(
        f"{NEXUS_URL}/api/protocol/verify",
        json={
            "from_agent": from_agent,
            "query": QUERY,
            "capability": "text_analysis",
            "min_agents": 2,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


async def run_test(
    test_name: str,
    cheater_names: list[str],
    all_agent_ids: dict[str, str],
    client: httpx.AsyncClient,
    consumer_id: str,
) -> dict:
    """Run a verification test and return results."""
    result = await run_verification(client, consumer_id)

    verdict = result.get("verdict", "?")
    score = result.get("consensus_score", 0)
    contradictions = result.get("contradictions", [])
    answers = result.get("answers", [])

    # Determine if cheater was caught
    # "caught" = verdict is FAIL or INCONCLUSIVE (not PASS)
    caught = verdict != "pass"

    return {
        "test": test_name,
        "cheaters": cheater_names,
        "verdict": verdict,
        "score": score,
        "contradictions": contradictions,
        "caught": caught,
        "answers": answers,
    }


# ═══════════════════════════════════════════════════════════════════════
# Test Scenarios
# ═══════════════════════════════════════════════════════════════════════


TESTS = [
    {
        "name": "Dumb Liar",
        "desc": "Obvious garbage, high confidence",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "dumb-liar": PORT_DUMB_LIAR,
        },
        "cheaters": ["dumb-liar"],
        "expected": "caught",
    },
    {
        "name": "Plausible Liar",
        "desc": "Correct format, wrong facts (dates, numbers, penalties)",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "plausible-liar": PORT_PLAUSIBLE_LIAR,
        },
        "cheaters": ["plausible-liar"],
        "expected": "caught",
    },
    {
        "name": "Partial Cheater",
        "desc": "80% correct, only penalty numbers are wrong",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "partial-cheater": PORT_PARTIAL_CHEATER,
        },
        "cheaters": ["partial-cheater"],
        "expected": "caught",
    },
    {
        "name": "Style Mimic",
        "desc": "Copies honest format exactly, changes country + currency",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "style-mimic": PORT_STYLE_MIMIC,
        },
        "cheaters": ["style-mimic"],
        "expected": "caught",
    },
    {
        "name": "Lazy Agent",
        "desc": "Generic fluff, no specific data, not obviously wrong",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "lazy-agent": PORT_LAZY_AGENT,
        },
        "cheaters": ["lazy-agent"],
        "expected": "caught",
    },
    {
        "name": "Confidence Gamer",
        "desc": "Mediocre output but 99% confidence to bias weighted score",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "honest-analyst-2": PORT_HONEST_2,
            "confidence-gamer": PORT_CONFIDENCE_GAMER,
        },
        "cheaters": ["confidence-gamer"],
        "expected": "caught",
    },
    {
        "name": "Colluding Pair",
        "desc": "Two agents agree on the same wrong answer vs 1 honest",
        "agents": {
            "honest-analyst-1": PORT_HONEST_1,
            "colluder-1": PORT_COLLUDER_1,
            "colluder-2": PORT_COLLUDER_2,
        },
        "cheaters": ["colluder-1", "colluder-2"],
        "expected": "should_fail",  # Nexus SHOULD fail here but probably won't
    },
]


async def run_all_tests():
    banner("NEXUS RED TEAM SUITE")
    info("Testing 7 adversarial agent types against Nexus verification.\n")

    # ── Start all servers ────────────────────────────────────────
    section("Starting servers...")

    procs = []

    # Nexus
    p = multiprocessing.Process(target=run_nexus, daemon=True)
    p.start()
    procs.append(p)

    # Agent servers
    agent_servers = [
        (create_honest_app, PORT_HONEST_1, "honest-analyst-1"),
        (create_honest_app, PORT_HONEST_2, "honest-analyst-2"),
        (create_dumb_liar_app, PORT_DUMB_LIAR),
        (create_plausible_liar_app, PORT_PLAUSIBLE_LIAR),
        (create_partial_cheater_app, PORT_PARTIAL_CHEATER),
        (create_style_mimic_app, PORT_STYLE_MIMIC),
        (create_lazy_agent_app, PORT_LAZY_AGENT),
        (create_confidence_gamer_app, PORT_CONFIDENCE_GAMER),
        (create_colluder_app, PORT_COLLUDER_1, "colluder-1"),
        (create_colluder_app, PORT_COLLUDER_2, "colluder-2"),
    ]

    for entry in agent_servers:
        factory = entry[0]
        port = entry[1]
        args = entry[2:] if len(entry) > 2 else ()
        p = multiprocessing.Process(target=_run, args=(factory, port, *args), daemon=True)
        p.start()
        procs.append(p)

    # Wait for Nexus
    if not await wait_for_server(f"{NEXUS_URL}/health"):
        print(f"  {RED}Nexus failed to start{RESET}")
        for p in procs:
            p.terminate()
        return

    info(f"Nexus + {len(agent_servers)} agents started.")

    try:
        async with httpx.AsyncClient() as client:
            # Register all agents
            section("Registering agents...")

            all_ids = {}
            all_agents = {
                "honest-analyst-1": PORT_HONEST_1,
                "honest-analyst-2": PORT_HONEST_2,
                "dumb-liar": PORT_DUMB_LIAR,
                "plausible-liar": PORT_PLAUSIBLE_LIAR,
                "partial-cheater": PORT_PARTIAL_CHEATER,
                "style-mimic": PORT_STYLE_MIMIC,
                "lazy-agent": PORT_LAZY_AGENT,
                "confidence-gamer": PORT_CONFIDENCE_GAMER,
                "colluder-1": PORT_COLLUDER_1,
                "colluder-2": PORT_COLLUDER_2,
            }

            for name, port in all_agents.items():
                if not await wait_for_server(f"http://localhost:{port}/health", timeout=10.0):
                    print(f"  {RED}Failed to start {name} on port {port}{RESET}")
                    continue
                agent_id = await register_agent(client, name, port)
                all_ids[name] = agent_id
                info(f"  {name}: {agent_id}")

            # Register consumer
            consumer_resp = await client.post(
                f"{NEXUS_URL}/api/registry/agents",
                json={
                    "name": "red-team-consumer",
                    "endpoint": "http://localhost:9999",
                    "description": "Red team test consumer",
                    "capabilities": [{"name": "testing", "description": "test", "price_per_request": 0.0}],
                },
            )
            consumer_resp.raise_for_status()
            consumer_data = consumer_resp.json()
            consumer_id = consumer_data.get("agent_id") or consumer_data.get("id")

            # ── Run tests ────────────────────────────────────────
            results = []

            for i, test in enumerate(TESTS, 1):
                section(f"Test {i}/7: {test['name']}")
                info(test["desc"])

                # For each test, we need verification to query the right set of agents.
                # Since verify queries ALL agents with text_analysis capability,
                # the results include all registered agents, not just the test set.
                # This is actually MORE realistic — the cheater hides among many agents.

                result = await run_test(
                    test["name"],
                    test["cheaters"],
                    all_ids,
                    client,
                    consumer_id,
                )
                results.append(result)

                # Display result
                verdict = result["verdict"]
                score = result["score"]
                caught = result["caught"]

                verdict_str = f"{GREEN}CAUGHT{RESET}" if caught else f"{RED}ESCAPED{RESET}"

                print(f"  Verdict: {BOLD}{verdict.upper()}{RESET}  |  Consensus: {score:.0%}  |  Result: {verdict_str}")

                if result["contradictions"]:
                    for c in result["contradictions"][:3]:
                        info(f"    Contradiction: {c}")

                # Small delay between tests to avoid idempotency issues
                await asyncio.sleep(0.5)

            # ══════════════════════════════════════════════════════
            # SCORECARD
            # ══════════════════════════════════════════════════════
            banner("RED TEAM SCORECARD", MAGENTA)

            caught_count = sum(1 for r in results if r["caught"])
            escaped_count = len(results) - caught_count

            print(f"\n  {BOLD}{'Test':<25} {'Verdict':<15} {'Score':<10} {'Result':<12}{RESET}")
            print(f"  {'-' * 62}")

            for r in results:
                verdict = r["verdict"].upper()
                score = f"{r['score']:.0%}"
                result_str = f"{GREEN}CAUGHT{RESET}" if r["caught"] else f"{RED}ESCAPED{RESET}"
                print(f"  {r['test']:<25} {verdict:<15} {score:<10} {result_str}")

            print(f"  {'-' * 62}")
            print(f"  {BOLD}Caught: {caught_count}/7  |  Escaped: {escaped_count}/7{RESET}")
            print()

            # Analysis
            if escaped_count > 0:
                banner("VULNERABILITIES FOUND", RED)
                print()
                for r in results:
                    if not r["caught"]:
                        escaped(f"{r['test']}: verdict={r['verdict']}, score={r['score']:.2f}")

                print(f"""
  {RED}{BOLD}Nexus verification has blind spots.{RESET}
  {DIM}These cheater types passed verification and would have been paid.{RESET}
  {DIM}The verification system needs hardening before production use.{RESET}
""")
            else:
                banner("ALL CHEATERS CAUGHT", GREEN)
                print(f"""
  {GREEN}{BOLD}Nexus caught every adversarial agent type.{RESET}
  {DIM}Verification held up under adversarial conditions.{RESET}
""")

            # Technical notes
            section("Technical Analysis")
            info("Verification method: text_similarity (SequenceMatcher)")
            info("PASS threshold: >= 0.6 consensus score")
            info("FAIL threshold: < 0.3 consensus score")
            info(f"Total agents in pool: {len(all_ids)}")
            info(f"Honest agents: 2  |  Adversarial agents: {len(all_ids) - 2}")
            print()

            # Recommendations
            if escaped_count > 0:
                section("Recommendations for hardening")
                info("1. Add semantic verification (embeddings, not just string matching)")
                info("2. Fact extraction + cross-check against query content")
                info("3. Cap confidence weight to prevent gaming")
                info("4. Detect collusion via response timing + similarity clustering")
                info("5. Require minimum 3 agents for consensus (not 2)")
                info("6. Add 'lazy detection' -- flag responses missing required data points")
                print()

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
        asyncio.run(run_all_tests())
    except KeyboardInterrupt:
        print(f"\n{DIM}Red team interrupted.{RESET}")
