"""
Nexus Demo Provider Agent — echo-provider

Runs on port 9501. Provides "echo" and "text_analysis" capabilities.
Registers with the Nexus registry on startup and sends periodic heartbeats.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_PORT = 9501
NEXUS_URL = "http://localhost:9500"
AGENT_NAME = "echo-provider"
AGENT_ENDPOINT = f"http://localhost:{AGENT_PORT}"
HEARTBEAT_INTERVAL_S = 30

logger = logging.getLogger(AGENT_NAME)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NexusRequest(BaseModel):
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


class NexusResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = ""
    from_agent: str = AGENT_NAME
    to_agent: str | None = ""
    status: str = "completed"
    answer: str = ""
    confidence: float = 1.0
    sources: list[str] = Field(default_factory=list)
    cost: float = 0.0
    processing_ms: int = 0
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ---------------------------------------------------------------------------
# Registration payload
# ---------------------------------------------------------------------------

REGISTRATION_PAYLOAD: dict[str, Any] = {
    "name": AGENT_NAME,
    "description": "Demo provider agent that echoes queries and performs basic text analysis.",
    "endpoint": AGENT_ENDPOINT,
    "capabilities": [
        {
            "name": "text_analysis",
            "description": "Analyzes and summarizes text",
            "price_per_request": 0.01,
            "avg_response_ms": 500,
            "languages": ["en", "de"],
        },
        {
            "name": "echo",
            "description": "Echoes back the query with analysis",
            "price_per_request": 0.0,
            "avg_response_ms": 100,
            "languages": ["en", "de"],
        },
    ],
    "tags": ["demo", "echo", "text-analysis", "provider"],
}

# ---------------------------------------------------------------------------
# Capability handlers
# ---------------------------------------------------------------------------


def _detect_language(text: str) -> str:
    """Heuristic language detection (German vs English)."""
    german_markers = [
        "der",
        "die",
        "das",
        "und",
        "ist",
        "ein",
        "eine",
        "nicht",
        "ich",
        "sie",
        "es",
        "wir",
        "auf",
        "mit",
        "den",
        "dem",
    ]
    words = re.findall(r"\w+", text.lower())
    if not words:
        return "unknown"
    german_hits = sum(1 for w in words if w in german_markers)
    ratio = german_hits / len(words)
    if ratio > 0.15:
        return "de"
    return "en"


def handle_echo(req: NexusRequest) -> NexusResponse:
    """Echo the query back with minimal decoration."""
    start = time.perf_counter_ns()
    answer = f"Echo: {req.query}"
    elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
    return NexusResponse(
        request_id=req.request_id,
        to_agent=req.from_agent,
        answer=answer,
        confidence=1.0,
        cost=0.0,
        processing_ms=elapsed_ms,
        meta={"capability": "echo"},
    )


def handle_text_analysis(req: NexusRequest) -> NexusResponse:
    """Return a mock text analysis with word/char counts and language detection."""
    start = time.perf_counter_ns()
    text = req.query
    words = text.split()
    word_count = len(words)
    char_count = len(text)
    detected_lang = _detect_language(text)
    sentence_count = max(1, len(re.split(r"[.!?]+", text.strip())) - 1) or 1
    avg_word_len = round(sum(len(w) for w in words) / max(word_count, 1), 1)

    summary = " ".join(words[:20]) + ("..." if word_count > 20 else "")

    answer = (
        f"Text Analysis Results:\n"
        f"  Words:            {word_count}\n"
        f"  Characters:       {char_count}\n"
        f"  Sentences:        {sentence_count}\n"
        f"  Avg word length:  {avg_word_len}\n"
        f"  Detected language: {detected_lang}\n"
        f"  Summary:          {summary}"
    )

    elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
    return NexusResponse(
        request_id=req.request_id,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.85,
        cost=0.01,
        processing_ms=elapsed_ms,
        sources=["internal-analysis"],
        meta={
            "capability": "text_analysis",
            "word_count": word_count,
            "char_count": char_count,
            "sentence_count": sentence_count,
            "avg_word_length": avg_word_len,
            "detected_language": detected_lang,
        },
    )


CAPABILITY_HANDLERS = {
    "echo": handle_echo,
    "text_analysis": handle_text_analysis,
}

# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

_agent_id: str | None = None
_heartbeat_task: asyncio.Task[None] | None = None


async def _register_with_nexus() -> None:
    """Register this agent with the Nexus registry."""
    global _agent_id
    url = f"{NEXUS_URL}/api/registry/agents"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(url, json=REGISTRATION_PAYLOAD)
            resp.raise_for_status()
            data = resp.json()
            _agent_id = data.get("agent_id") or data.get("id")
            logger.info("Registered with Nexus  agent_id=%s", _agent_id)
        except httpx.HTTPError as exc:
            logger.error("Registration failed: %s", exc)


async def _heartbeat_loop() -> None:
    """Send periodic heartbeats to Nexus."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        if _agent_id is None:
            logger.warning("No agent_id yet — skipping heartbeat")
            continue
        url = f"{NEXUS_URL}/api/registry/agents/{_agent_id}/heartbeat"
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                resp = await client.post(url)
                resp.raise_for_status()
                logger.debug("Heartbeat sent  agent_id=%s", _agent_id)
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed: %s", exc)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _heartbeat_task
    await _register_with_nexus()
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info("Provider agent started on port %d", AGENT_PORT)
    yield
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await _heartbeat_task
    logger.info("Provider agent shut down")


app = FastAPI(
    title="Nexus Echo-Provider",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/nexus/handle")
async def handle_nexus_request(req: NexusRequest) -> NexusResponse:
    """Process an incoming NexusRequest and return a NexusResponse."""
    logger.info(
        "Received request  id=%s  capability=%s  from=%s",
        req.request_id,
        req.capability,
        req.from_agent,
    )

    handler = CAPABILITY_HANDLERS.get(req.capability)
    if handler is None:
        logger.warning("Unknown capability: %s", req.capability)
        return NexusResponse(
            request_id=req.request_id,
            to_agent=req.from_agent,
            status="failed",
            answer="",
            confidence=0.0,
            error=f"Unsupported capability: {req.capability}",
        )

    response = handler(req)
    logger.info(
        "Processed request  id=%s  status=%s  ms=%d",
        req.request_id,
        response.status,
        response.processing_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.provider:app",
        host="0.0.0.0",
        port=AGENT_PORT,
        log_level="info",
    )
