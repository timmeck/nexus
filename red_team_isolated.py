"""
Nexus Red Team Suite v2 — Isolated Tests.

Each test runs with a fresh Nexus instance and ONLY the relevant agents.
This gives clean, per-cheater-type results.

Usage:
    python red_team_isolated.py
"""

from __future__ import annotations

import asyncio
import contextlib
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
# Config
# ═══════════════════════════════════════════════════════════════════════

NEXUS_URL = "http://localhost:9500"
NEXUS_PORT = 9500

# ═══════════════════════════════════════════════════════════════════════
# Terminal
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
# Test Query
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
# Agent Factories
# ═══════════════════════════════════════════════════════════════════════


def _honest_answer(req: AgentRequest, name: str, variation: int = 0) -> AgentResponse:
    text = req.query
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text
    words = analyze_text.split()
    word_count = len(words)
    char_count = len(analyze_text)
    sentence_count = len([s for s in re.split(r"[.!?]+", analyze_text.strip()) if s.strip()])

    if variation == 0:
        answer = (
            f"Text Analysis Results:\n"
            f"  Word count: {word_count}\n"
            f"  Character count: {char_count}\n"
            f"  Sentence count: {sentence_count}\n"
            f"  Summary: The EU announced the AI Act on March 15, 2025, requiring "
            f"conformity assessments for high-risk AI systems. Companies have 24 months "
            f"to comply, with penalties up to 35 million euros or 7% of global turnover."
        )
    else:
        answer = (
            f"Analysis Report:\n"
            f"  Words: {word_count}\n"
            f"  Characters: {char_count}\n"
            f"  Sentences: {sentence_count}\n"
            f"  Summary: On March 15, 2025, the EU released the AI Act mandating "
            f"conformity assessments for high-risk AI. The compliance deadline is 24 months, "
            f"with fines reaching 35 million euros or 7% of annual global turnover."
        )

    return AgentResponse(
        request_id=req.request_id,
        from_agent=name,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.88 if variation == 0 else 0.86,
        cost=0.05,
        processing_ms=150,
    )


def _honest_verbose(req: AgentRequest, name: str) -> AgentResponse:
    """Honest agent with very different, verbose style. Same facts."""
    text = req.query
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text
    words = analyze_text.split()

    answer = (
        f"I've completed a thorough analysis of the provided text. "
        f"Here are the key metrics: the text contains {len(words)} words "
        f"spread across {len(analyze_text)} characters in approximately 5 sentences. "
        f"The content discusses the European Union's AI Act, announced on March 15, 2025. "
        f"Key takeaway: companies face a 24-month compliance window, with penalties "
        f"reaching 35 million euros or 7% of global annual turnover for non-compliance."
    )

    return AgentResponse(
        request_id=req.request_id,
        from_agent=name,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.82,
        cost=0.05,
        processing_ms=200,
    )


def _honest_minimal(req: AgentRequest, name: str) -> AgentResponse:
    """Honest agent with ultra-minimal style. Same facts, fewer words."""
    text = req.query
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text
    words = analyze_text.split()

    answer = (
        f"Words: {len(words)}. Chars: {len(analyze_text)}. Sentences: 5. "
        f"EU AI Act (March 15, 2025): conformity assessments required. "
        f"24mo deadline. Penalty: EUR 35M / 7% turnover."
    )

    return AgentResponse(
        request_id=req.request_id,
        from_agent=name,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.91,
        cost=0.05,
        processing_ms=60,
    )


def _honest_german_style(req: AgentRequest, name: str) -> AgentResponse:
    """Honest agent answering in English but with different terminology. Same facts."""
    text = req.query
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text
    words = analyze_text.split()

    answer = (
        f"Text evaluation:\n"
        f"  Word total: {len(words)}\n"
        f"  Character total: {len(analyze_text)}\n"
        f"  Number of sentences: 5\n"
        f"  Overview: The European Union published the AI Act regulation "
        f"on 15 March 2025. High-risk AI systems must pass conformity "
        f"assessments. The compliance period is 24 months. Maximum fine: "
        f"35 million euros or 7 percent of worldwide annual revenue."
    )

    return AgentResponse(
        request_id=req.request_id,
        from_agent=name,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.84,
        cost=0.05,
        processing_ms=170,
    )


def make_app(name: str, handler_fn) -> FastAPI:
    app = FastAPI(title=name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": name}

    @app.post("/nexus/handle")
    async def handle(req: AgentRequest) -> AgentResponse:
        return handler_fn(req)

    return app


# ── Cheater handlers ─────────────────────────────────────────────


def dumb_liar_handler(req: AgentRequest) -> AgentResponse:
    """Obvious garbage, high confidence."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="dumb-liar",
        to_agent=req.from_agent,
        answer="Analysis complete. Everything looks great. No issues found. Trust me.",
        confidence=0.95,
        cost=0.05,
        processing_ms=30,
    )


def plausible_liar_handler(req: AgentRequest) -> AgentResponse:
    """Correct structure, wrong facts."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="plausible-liar",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  Word count: 84\n"
            "  Character count: 502\n"
            "  Sentence count: 6\n"
            "  Summary: The EU announced the AI Act on June 20, 2025, requiring "
            "conformity assessments for high-risk AI systems. Companies have 18 months "
            "to comply, with penalties up to 20 million euros or 4% of global turnover."
        ),
        confidence=0.87,
        cost=0.05,
        processing_ms=140,
    )


def partial_cheater_handler(req: AgentRequest) -> AgentResponse:
    """80% correct, wrong penalty numbers only."""
    text = req.query
    parts = text.split("\n\n", 1)
    analyze_text = parts[1] if len(parts) > 1 else text
    words = analyze_text.split()
    return AgentResponse(
        request_id=req.request_id,
        from_agent="partial-cheater",
        to_agent=req.from_agent,
        answer=(
            f"Text Analysis Results:\n"
            f"  Word count: {len(words)}\n"
            f"  Character count: {len(analyze_text)}\n"
            f"  Sentence count: 5\n"
            f"  Summary: The EU announced the AI Act on March 15, 2025, requiring "
            f"conformity assessments for high-risk AI systems. Companies have 24 months "
            f"to comply, with penalties up to 50 million euros or 10% of global turnover."
        ),
        confidence=0.90,
        cost=0.05,
        processing_ms=130,
    )


def style_mimic_handler(req: AgentRequest) -> AgentResponse:
    """Exact same format, changes EU->US, euros->dollars."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="style-mimic",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  Word count: 81\n"
            "  Character count: 486\n"
            "  Sentence count: 5\n"
            "  Summary: The US announced the AI Safety Act on March 15, 2025, requiring "
            "safety evaluations for high-risk AI systems. Companies have 24 months "
            "to comply, with penalties up to 35 million dollars or 7% of global turnover."
        ),
        confidence=0.87,
        cost=0.05,
        processing_ms=145,
    )


def lazy_agent_handler(req: AgentRequest) -> AgentResponse:
    """Generic fluff, no specific data."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="lazy-agent",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  The provided text discusses recent regulatory developments "
            "in artificial intelligence policy. It contains multiple sentences "
            "covering various aspects of compliance requirements and potential "
            "penalties for organizations operating in this space."
        ),
        confidence=0.72,
        cost=0.05,
        processing_ms=80,
    )


def confidence_gamer_handler(req: AgentRequest) -> AgentResponse:
    """Vague output, 99% confidence to bias weighted score."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="confidence-gamer",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  Word count: 79\n"
            "  Character count: 480\n"
            "  Sentence count: 4\n"
            "  Summary: New AI regulations were announced requiring compliance "
            "assessments. Companies must comply within a set timeframe or face "
            "significant financial penalties based on their revenue."
        ),
        confidence=0.99,
        cost=0.05,
        processing_ms=90,
    )


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


def colluder_handler(name: str):
    def handler(req: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=req.request_id,
            from_agent=name,
            to_agent=req.from_agent,
            answer=COLLUDING_ANSWER,
            confidence=0.88,
            cost=0.05,
            processing_ms=135,
        )

    return handler


# ═══════════════════════════════════════════════════════════════════════
# RED TEAM v3: New adversarial patterns
# ═══════════════════════════════════════════════════════════════════════


def omission_handler(req: AgentRequest) -> AgentResponse:
    """Omission Attack: correct structure, but leaves out all specific numbers/dates.
    No claims to extract = no mismatches to detect."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="omission-agent",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  Word count: (see below)\n"
            "  Character count: (see below)\n"
            "  Sentence count: (see below)\n"
            "  Summary: The European Union announced new regulations on artificial "
            "intelligence. The AI Act requires high-risk AI systems to undergo "
            "conformity assessments before deployment. Companies have a defined period "
            "to comply. Penalties for non-compliance can be substantial, based on "
            "global annual turnover."
        ),
        confidence=0.82,
        cost=0.05,
        processing_ms=120,
    )


def word_number_handler(req: AgentRequest) -> AgentResponse:
    """Adversarial Formatting: writes numbers as words to bypass regex extraction.
    'thirty five million' instead of '35 million'."""
    return AgentResponse(
        request_id=req.request_id,
        from_agent="word-number-agent",
        to_agent=req.from_agent,
        answer=(
            "Text Analysis Results:\n"
            "  Word count: eighty one\n"
            "  Character count: four hundred eighty six\n"
            "  Sentence count: five\n"
            "  Summary: The EU announced the AI Act on March fifteenth, twenty twenty five, "
            "requiring conformity assessments for high-risk AI systems. Companies have "
            "twenty four months to comply, with penalties up to fifty million euros or "
            "ten percent of global turnover."
        ),
        confidence=0.85,
        cost=0.05,
        processing_ms=140,
    )


def colluder_v2_handler(name: str):
    """Collusion v2: coordinated but NOT identical wrong answers.
    Both wrong on the same facts but with slight variation."""

    def handler(req: AgentRequest) -> AgentResponse:
        if "1" in name:
            answer = (
                "Text Analysis Results:\n"
                "  Word count: 78\n"
                "  Character count: 470\n"
                "  Sentence count: 5\n"
                "  Summary: The EU announced the AI Act on March 15, 2025, requiring "
                "conformity assessments for high-risk AI systems. Companies have 18 months "
                "to comply, with penalties up to 50 million euros or 10% of global turnover."
            )
        else:
            answer = (
                "Text Analysis Results:\n"
                "  Word count: 79\n"
                "  Character count: 475\n"
                "  Sentence count: 5\n"
                "  Summary: The EU released the AI Act on March 15, 2025, mandating "
                "conformity assessments for high-risk AI systems. Companies have 18 months "
                "to comply, with fines up to 50 million euros or 10% of annual global revenue."
            )
        return AgentResponse(
            request_id=req.request_id,
            from_agent=name,
            to_agent=req.from_agent,
            answer=answer,
            confidence=0.87,
            cost=0.05,
            processing_ms=130,
        )

    return handler


# ═══════════════════════════════════════════════════════════════════════
# Server management
# ═══════════════════════════════════════════════════════════════════════


def _build_app(agent_type: str, agent_name: str) -> FastAPI:
    """Build a FastAPI app for the given agent type."""
    handlers = {
        "honest-0": lambda r: _honest_answer(r, agent_name, 0),
        "honest-1": lambda r: _honest_answer(r, agent_name, 1),
        "honest-verbose": lambda r: _honest_verbose(r, agent_name),
        "honest-minimal": lambda r: _honest_minimal(r, agent_name),
        "honest-german": lambda r: _honest_german_style(r, agent_name),
        "dumb-liar": dumb_liar_handler,
        "plausible-liar": plausible_liar_handler,
        "partial-cheater": partial_cheater_handler,
        "style-mimic": style_mimic_handler,
        "lazy-agent": lazy_agent_handler,
        "confidence-gamer": confidence_gamer_handler,
        "colluder": colluder_handler(agent_name),
        "omission": omission_handler,
        "word-number": word_number_handler,
        "colluder-v2": colluder_v2_handler(agent_name),
    }
    return make_app(agent_name, handlers[agent_type])


def run_agent_server(agent_type: str, agent_name: str, port: int):
    """Subprocess target for running an agent server."""
    app = _build_app(agent_type, agent_name)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def run_nexus_server():
    from nexus.main import app

    uvicorn.run(app, host="127.0.0.1", port=NEXUS_PORT, log_level="error")


async def wait_for(url: str, timeout: float = 15.0) -> bool:
    start = time.time()
    async with httpx.AsyncClient() as c:
        while time.time() - start < timeout:
            try:
                r = await c.get(url, timeout=2.0)
                if r.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(0.3)
    return False


async def register(client: httpx.AsyncClient, name: str, port: int) -> str:
    resp = await client.post(
        f"{NEXUS_URL}/api/registry/agents",
        json={
            "name": name,
            "endpoint": f"http://localhost:{port}",
            "description": f"Red team: {name}",
            "capabilities": [
                {
                    "name": "text_analysis",
                    "description": "Analyzes text",
                    "price_per_request": 0.05,
                    "avg_response_ms": 500,
                    "languages": ["en"],
                }
            ],
            "tags": ["red-team"],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("agent_id") or data.get("id")


async def verify(client: httpx.AsyncClient, from_agent: str) -> dict:
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


# ═══════════════════════════════════════════════════════════════════════
# Test definitions
# ═══════════════════════════════════════════════════════════════════════


TESTS = [
    {
        "name": "Baseline: 2 honest agents",
        "desc": "Control test -- two honest agents should reach consensus (PASS)",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
        ],
        "cheaters": [],
        "expected_verdict": "pass",
    },
    {
        "name": "Dumb Liar",
        "desc": "Obvious garbage with 95% confidence vs 2 honest agents",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("dumb-liar", 9803, "dumb-liar"),
        ],
        "cheaters": ["dumb-liar"],
        "expected_verdict": "fail",
    },
    {
        "name": "Plausible Liar",
        "desc": "Correct format, wrong dates/numbers/penalties",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("plausible-liar", 9803, "plausible-liar"),
        ],
        "cheaters": ["plausible-liar"],
        "expected_verdict": "fail",
    },
    {
        "name": "Partial Cheater",
        "desc": "80% correct, only penalty numbers wrong (50M/10% vs 35M/7%)",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("partial-cheater", 9803, "partial-cheater"),
        ],
        "cheaters": ["partial-cheater"],
        "expected_verdict": "fail",
    },
    {
        "name": "Style Mimic",
        "desc": "Exact format, changes EU->US, euros->dollars",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("style-mimic", 9803, "style-mimic"),
        ],
        "cheaters": ["style-mimic"],
        "expected_verdict": "fail",
    },
    {
        "name": "Lazy Agent",
        "desc": "Generic fluff, no data points, not obviously wrong",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("lazy-agent", 9803, "lazy-agent"),
        ],
        "cheaters": ["lazy-agent"],
        "expected_verdict": "fail",
    },
    {
        "name": "Confidence Gamer",
        "desc": "Vague output but 99% confidence to bias weighted consensus",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("confidence-gamer", 9803, "confidence-gamer"),
        ],
        "cheaters": ["confidence-gamer"],
        "expected_verdict": "fail",
    },
    {
        "name": "Colluding Pair vs 1 Honest",
        "desc": "2 agents agree on wrong answer, outnumber 1 honest agent",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("colluder-1", 9802, "colluder"),
            ("colluder-2", 9803, "colluder"),
        ],
        "cheaters": ["colluder-1", "colluder-2"],
        "expected_verdict": "pass_wrong",
    },
    {
        "name": "Colluding Pair vs 2 Honest",
        "desc": "2 colluders vs 2 honest -- can majority hold?",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("colluder-1", 9803, "colluder"),
            ("colluder-2", 9804, "colluder"),
        ],
        "cheaters": ["colluder-1", "colluder-2"],
        "expected_verdict": "inconclusive",
    },
    # ── RED TEAM v3: New adversarial patterns ──────────────────
    {
        "name": "Omission Attack",
        "desc": "Correct structure but ALL specific numbers/dates omitted",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("omission-agent", 9803, "omission"),
        ],
        "cheaters": ["omission-agent"],
        "expected_verdict": "fail",
    },
    {
        "name": "Word Numbers (Formatting)",
        "desc": "Numbers as words: 'thirty five million' to bypass regex",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("word-number-agent", 9803, "word-number"),
        ],
        "cheaters": ["word-number-agent"],
        "expected_verdict": "fail",
    },
    {
        "name": "Collusion v2 (Coordinated)",
        "desc": "2 cheaters agree on wrong facts but with slight variation (not identical)",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("colluder-v2-1", 9802, "colluder-v2"),
            ("colluder-v2-2", 9803, "colluder-v2"),
        ],
        "cheaters": ["colluder-v2-1", "colluder-v2-2"],
        "expected_verdict": "fail",
    },
    # ── FALSE POSITIVE TESTS ──────────────────────────────────
    # Honest agents with very different styles. Must NOT be flagged.
    {
        "name": "FP: Verbose vs Standard",
        "desc": "Same facts, very different writing style (verbose prose vs structured)",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-verbose", 9802, "honest-verbose"),
        ],
        "cheaters": [],
        "expected_verdict": "pass",
    },
    {
        "name": "FP: Minimal vs Standard",
        "desc": "Same facts, ultra-short telegraphic style (EUR 35M / 7%)",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-minimal", 9802, "honest-minimal"),
        ],
        "cheaters": [],
        "expected_verdict": "pass",
    },
    {
        "name": "FP: All 4 Honest Styles",
        "desc": "4 honest agents, all different styles, same facts. Must all agree.",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-2", 9802, "honest-1"),
            ("honest-verbose", 9803, "honest-verbose"),
            ("honest-minimal", 9804, "honest-minimal"),
        ],
        "cheaters": [],
        "expected_verdict": "pass",
    },
    {
        "name": "FP: German-style vs Standard",
        "desc": "Different terminology (Word total, Overview, 15 March 2025), same facts",
        "agents": [
            ("honest-1", 9801, "honest-0"),
            ("honest-german", 9802, "honest-german"),
        ],
        "cheaters": [],
        "expected_verdict": "pass",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Run isolated test
# ═══════════════════════════════════════════════════════════════════════


async def run_single_test(test: dict, test_num: int, total: int) -> dict:
    """Run one test with fresh Nexus + only the specified agents."""
    import os

    section(f"Test {test_num}/{total}: {test['name']}")
    print(f"  {DIM}{test['desc']}{RESET}")

    # Clean DB for fresh state
    db_path = os.path.join("data", "nexus.db")
    with contextlib.suppress(OSError):
        os.remove(db_path)

    procs = []

    # Start Nexus
    nexus_proc = multiprocessing.Process(target=run_nexus_server, daemon=True)
    nexus_proc.start()
    procs.append(nexus_proc)

    # Start agent servers
    for name, port, agent_type in test["agents"]:
        p = multiprocessing.Process(
            target=run_agent_server,
            args=(agent_type, name, port),
            daemon=True,
        )
        p.start()
        procs.append(p)

    try:
        # Wait for all servers
        if not await wait_for(f"{NEXUS_URL}/health"):
            print(f"  {RED}Nexus failed to start{RESET}")
            return {"test": test["name"], "verdict": "error", "score": 0, "caught": False}

        for name, port, _ in test["agents"]:
            if not await wait_for(f"http://localhost:{port}/health", timeout=10.0):
                print(f"  {RED}{name} failed to start{RESET}")
                return {"test": test["name"], "verdict": "error", "score": 0, "caught": False}

        async with httpx.AsyncClient() as client:
            # Register agents
            for name, port, _type in test["agents"]:
                await register(client, name, port)

            # Register consumer
            consumer_resp = await client.post(
                f"{NEXUS_URL}/api/registry/agents",
                json={
                    "name": "test-consumer",
                    "endpoint": "http://localhost:9999",
                    "description": "test",
                    "capabilities": [{"name": "testing", "description": "t", "price_per_request": 0.0}],
                },
            )
            consumer_data = consumer_resp.json()
            consumer_id = consumer_data.get("agent_id") or consumer_data.get("id")

            # Run verification
            result = await verify(client, consumer_id)

            verdict = result.get("verdict", "?")
            score = result.get("consensus_score", 0)
            contradictions = result.get("contradictions", [])
            answers = result.get("answers", [])

            # Determine caught status for cheater tests
            expected = test["expected_verdict"]
            if not test["cheaters"]:
                caught = verdict == "pass"
                caught_label = "PASS" if caught else "FALSE NEGATIVE"
                caught_color = GREEN if caught else RED
            elif expected == "pass_wrong":
                if verdict == "pass":
                    caught = False
                    caught_label = "FOOLED"
                    caught_color = RED
                else:
                    caught = True
                    caught_label = "CAUGHT"
                    caught_color = GREEN
            else:
                caught = verdict != "pass"
                caught_label = "CAUGHT" if caught else "ESCAPED"
                caught_color = GREEN if caught else RED

            # Print results
            verdict_color = GREEN if verdict == "pass" else (RED if verdict == "fail" else YELLOW)
            print(
                f"  Verdict: {BOLD}{verdict_color}{verdict.upper()}{RESET}  |  "
                f"Consensus: {score:.0%}  |  "
                f"Agents: {result.get('agents_responded', '?')}/{result.get('agents_queried', '?')}  |  "
                f"Result: {caught_color}{BOLD}{caught_label}{RESET}"
            )

            # Show per-agent answers
            if answers:
                for a in answers:
                    name = a.get("agent_name", "?")
                    conf = a.get("confidence", 0)
                    ans_preview = a.get("answer", "")[:60].replace("\n", " ")
                    is_cheater = name in test["cheaters"]
                    marker = f"{RED}*{RESET}" if is_cheater else " "
                    print(f'    {marker} {name:<20} conf={conf:.0%}  "{ans_preview}..."')

            if contradictions:
                for c in contradictions[:2]:
                    print(f"    {DIM}Contradiction: {c}{RESET}")

            return {
                "test": test["name"],
                "verdict": verdict,
                "score": score,
                "caught": caught,
                "caught_label": caught_label,
                "expected": expected,
                "contradictions": len(contradictions),
                "agents": len(test["agents"]),
                "cheaters": len(test["cheaters"]),
            }

    finally:
        for p in procs:
            p.terminate()
            p.join(timeout=3)
        await asyncio.sleep(1.0)  # let ports release


async def run_all():
    banner("NEXUS RED TEAM v2 -- Isolated Tests")
    print(f"  {DIM}Each test runs with fresh Nexus + only the relevant agents.{RESET}")
    print(f"  {DIM}16 tests: 1 baseline + 11 cheaters + 4 false-positive tests.{RESET}")

    results = []

    for i, test in enumerate(TESTS, 1):
        result = await run_single_test(test, i, len(TESTS))
        results.append(result)

    # ═══════════════════════════════════════════════════════════════
    # SCORECARD
    # ═══════════════════════════════════════════════════════════════
    banner("RED TEAM SCORECARD", MAGENTA)

    print(f"\n  {BOLD}{'Test':<30} {'Agents':<8} {'Verdict':<15} {'Score':<8} {'Result':<12}{RESET}")
    print(f"  {'-' * 73}")

    for r in results:
        verdict = r["verdict"].upper()
        score = f"{r['score']:.0%}"
        agents = f"{r['agents']}a"
        label = r.get("caught_label", "?")

        if label in ("CAUGHT", "PASS"):
            color = GREEN
        elif label in ("ESCAPED", "FOOLED", "FALSE NEGATIVE"):
            color = RED
        else:
            color = YELLOW

        print(f"  {r['test']:<30} {agents:<8} {verdict:<15} {score:<8} {color}{BOLD}{label}{RESET}")

    print(f"  {'-' * 73}")

    # Summary
    cheater_tests = [r for r in results if r["cheaters"] > 0]
    caught = sum(1 for r in cheater_tests if r["caught"])
    escaped = len(cheater_tests) - caught

    baseline = [r for r in results if r["cheaters"] == 0]
    baseline_pass = sum(1 for r in baseline if r["caught"])

    print(
        f"\n  {BOLD}Baseline:{RESET} {'PASS' if baseline_pass else 'FAIL'} "
        f"(honest agents {'reached' if baseline_pass else 'failed to reach'} consensus)"
    )
    print(f"  {BOLD}Cheater tests:{RESET} Caught {caught}/{len(cheater_tests)}, Escaped {escaped}/{len(cheater_tests)}")

    if escaped > 0:
        banner("VULNERABILITIES FOUND", RED)
        for r in cheater_tests:
            if not r["caught"]:
                print(f"  {RED}[!!] {r['test']}: verdict={r['verdict']}, score={r['score']:.2f}{RESET}")

        print(f"\n  {DIM}These cheater types bypassed verification.{RESET}")
        print(f"  {DIM}The verification system needs hardening.{RESET}")
    else:
        banner("ALL CHEATERS CAUGHT", GREEN)
        print(f"  {GREEN}{BOLD}Every adversarial agent type was detected.{RESET}")

    # Recommendations
    section("Hardening Recommendations")
    recs = []
    for r in results:
        if r["test"] == "Baseline: 2 honest agents" and not r["caught"]:
            recs.append("CRITICAL: Honest agents can't reach consensus -- threshold or similarity algo needs work")
        if "Partial" in r["test"] and not r["caught"]:
            recs.append("Add fact extraction: compare specific numbers/dates, not just text similarity")
        if "Style Mimic" in r["test"] and not r["caught"]:
            recs.append("Add entity-level verification: check EU vs US, euros vs dollars")
        if "Confidence" in r["test"] and not r["caught"]:
            recs.append("Cap confidence weight in consensus calculation (e.g. max 0.5 influence)")
        if "Colluding" in r["test"] and not r["caught"]:
            recs.append("Detect collusion: flag identical/near-identical responses from different agents")
        if "Lazy" in r["test"] and not r["caught"]:
            recs.append("Add completeness check: flag responses missing required data points")
        if "Plausible" in r["test"] and not r["caught"]:
            recs.append("Add semantic verification: compare meaning, not just string overlap")

    if not recs:
        recs.append("All tests passed -- consider adding more sophisticated adversarial patterns")

    for i, rec in enumerate(recs, 1):
        print(f"  {i}. {rec}")
    print()

    # Cleanup
    import os

    with contextlib.suppress(OSError):
        os.remove(os.path.join("data", "nexus.db"))


# ═══════════════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        print(f"\n{DIM}Red team interrupted.{RESET}")
