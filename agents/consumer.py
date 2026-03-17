"""
Nexus Demo Consumer Agent — demo-consumer

Runs on port 9502. Delegates queries to other agents via the Nexus protocol layer.
Provides both a /nexus/handle endpoint and an interactive CLI mode.
"""

from __future__ import annotations

import asyncio
import logging
import sys
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

AGENT_PORT = 9502
NEXUS_URL = "http://localhost:9500"
AGENT_NAME = "demo-consumer"
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
    "description": "Demo consumer agent that delegates queries to other agents via Nexus.",
    "endpoint": AGENT_ENDPOINT,
    "capabilities": [
        {
            "name": "query_delegation",
            "description": "Delegates queries to other agents via Nexus",
            "price_per_request": 0.0,
            "avg_response_ms": 2000,
            "languages": ["en"],
        },
    ],
    "tags": ["demo", "consumer", "delegation"],
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
# Nexus protocol helpers
# ---------------------------------------------------------------------------


async def send_nexus_request(
    query: str,
    to_agent: str = "echo-provider",
    capability: str = "echo",
    language: str = "en",
) -> dict[str, Any]:
    """Send a NexusRequest through the Nexus protocol layer and return the response."""
    url = f"{NEXUS_URL}/api/protocol/request"
    payload = {
        "from_agent": AGENT_NAME,
        "to_agent": to_agent,
        "query": query,
        "capability": capability,
        "language": language,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _heartbeat_task
    await _register_with_nexus()
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info("Consumer agent started on port %d", AGENT_PORT)
    yield
    if _heartbeat_task is not None:
        _heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await _heartbeat_task
    logger.info("Consumer agent shut down")


app = FastAPI(
    title="Nexus Demo-Consumer",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/nexus/handle")
async def handle_nexus_request(req: NexusRequest) -> NexusResponse:
    """Handle an incoming NexusRequest (e.g. from another agent)."""
    start = time.perf_counter_ns()
    logger.info(
        "Received request  id=%s  from=%s  capability=%s",
        req.request_id,
        req.from_agent,
        req.capability,
    )

    answer = (
        f"Consumer received query: '{req.query}'. In production this would be delegated to an appropriate provider."
    )
    elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000

    return NexusResponse(
        request_id=req.request_id,
        to_agent=req.from_agent,
        answer=answer,
        confidence=0.5,
        cost=0.0,
        processing_ms=elapsed_ms,
        meta={"capability": "query_delegation", "note": "demo-mode"},
    )


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

SEPARATOR = "-" * 60


def _print_response(data: dict[str, Any]) -> None:
    """Pretty-print a NexusResponse dict to the terminal."""
    print(f"\n{SEPARATOR}")
    print(f"  Status:      {data.get('status', 'unknown')}")
    print(f"  From:        {data.get('from_agent', '?')}")
    print(f"  Confidence:  {data.get('confidence', '?')}")
    print(f"  Cost:        {data.get('cost', '?')}")
    print(f"  Time (ms):   {data.get('processing_ms', '?')}")
    print(f"{SEPARATOR}")
    answer = data.get("answer", data.get("error", "(no answer)"))
    print(f"  {answer}")
    if data.get("sources"):
        print(f"  Sources: {', '.join(data['sources'])}")
    if data.get("error"):
        print(f"  Error: {data['error']}")
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# Interactive CLI mode
# ---------------------------------------------------------------------------


async def cli_loop() -> None:
    """Interactive loop: read user input, send to Nexus, print response."""
    # Register first (no server running in CLI mode)
    await _register_with_nexus()

    print("\n=== Nexus Demo Consumer — Interactive CLI ===")
    print("Commands:")
    print("  <query>                      — send to echo-provider (echo)")
    print("  analyze: <text>              — send to echo-provider (text_analysis)")
    print("  to:<agent> cap:<cap> <query> — custom target")
    print("  quit / exit                  — leave\n")

    while True:
        try:
            user_input = input("nexus> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        # Parse optional to: and cap: prefixes
        to_agent = "echo-provider"
        capability = "echo"
        query = user_input

        if user_input.lower().startswith("analyze:"):
            capability = "text_analysis"
            query = user_input[len("analyze:") :].strip()
        else:
            parts = user_input.split()
            remaining: list[str] = []
            for part in parts:
                if part.startswith("to:"):
                    to_agent = part[3:]
                elif part.startswith("cap:"):
                    capability = part[4:]
                else:
                    remaining.append(part)
            query = " ".join(remaining)

        if not query:
            print("Empty query — skipping.")
            continue

        print(f"  Sending to '{to_agent}' capability='{capability}' ...")
        try:
            result = await send_nexus_request(
                query=query,
                to_agent=to_agent,
                capability=capability,
            )
            _print_response(result)
        except httpx.HTTPStatusError as exc:
            print(f"  HTTP error: {exc.response.status_code} — {exc.response.text}")
        except httpx.HTTPError as exc:
            print(f"  Connection error: {exc}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--cli" in sys.argv:
        asyncio.run(cli_loop())
    else:
        uvicorn.run(
            "agents.consumer:app",
            host="0.0.0.0",
            port=AGENT_PORT,
            log_level="info",
        )
