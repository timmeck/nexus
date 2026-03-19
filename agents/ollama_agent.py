"""
Real Ollama-powered agent for Nexus integration testing.

Runs a FastAPI server that takes Nexus requests and forwards them to Ollama.
No mocking — real LLM inference.

Usage:
    python agents/ollama_agent.py [--port 9801] [--name agent-1] [--model qwen2.5]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
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
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5"
HEARTBEAT_INTERVAL = 30


# ═══════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════


class NexusRequest(BaseModel):
    request_id: str = ""
    from_agent: str = ""
    to_agent: str | None = None
    query: str = ""
    capability: str | None = None
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
    from_agent: str = ""
    to_agent: str | None = ""
    status: str = "completed"
    answer: str = ""
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)
    cost: float = 0.0
    processing_ms: int = 0
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ═══════════════════════════════════════════════════════════════════════
# Ollama Integration
# ═══════════════════════════════════════════════════════════════════════


async def query_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send a prompt to Ollama and return the response text."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


# ═══════════════════════════════════════════════════════════════════════
# Agent Factory
# ═══════════════════════════════════════════════════════════════════════


def create_agent(
    agent_name: str,
    port: int,
    model: str = DEFAULT_MODEL,
) -> FastAPI:
    agent_id: str | None = None
    heartbeat_task: asyncio.Task | None = None

    async def register():
        nonlocal agent_id
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{NEXUS_URL}/api/registry/agents",
                json={
                    "name": agent_name,
                    "endpoint": f"http://localhost:{port}",
                    "description": f"Real Ollama agent ({model}) for integration testing",
                    "capabilities": [
                        {
                            "name": "text_analysis",
                            "description": "Analyze text using real LLM inference",
                            "price_per_request": 0.02,
                            "avg_response_ms": 5000,
                            "languages": ["en"],
                        },
                    ],
                    "tags": ["ollama", "real-llm", model],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            agent_id = data.get("agent_id") or data.get("id")
            print(f"[{agent_name}] Registered with Nexus: {agent_id}")

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if agent_id:
                async with httpx.AsyncClient(timeout=5) as client:
                    with suppress(Exception):
                        await client.post(f"{NEXUS_URL}/api/registry/agents/{agent_id}/heartbeat")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal heartbeat_task
        try:
            await register()
        except Exception as e:
            print(f"[{agent_name}] Registration failed: {e}")
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        print(f"[{agent_name}] Running on port {port} with model {model}")
        yield
        if heartbeat_task:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    app = FastAPI(title=agent_name, lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": agent_name, "model": model}

    @app.post("/nexus/handle")
    async def handle(req: NexusRequest) -> NexusResponse:
        start = time.perf_counter_ns()

        try:
            # Real LLM inference via Ollama
            answer = await query_ollama(req.query, model=model)
            elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000

            return NexusResponse(
                request_id=req.request_id,
                from_agent=agent_name,
                to_agent=req.from_agent,
                status="completed",
                answer=answer.strip(),
                confidence=0.85,
                cost=0.02,
                processing_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
            return NexusResponse(
                request_id=req.request_id,
                from_agent=agent_name,
                to_agent=req.from_agent,
                status="failed",
                error=str(e),
                processing_ms=elapsed_ms,
            )

    return app


# ═══════════════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ollama-powered Nexus agent")
    parser.add_argument("--port", type=int, default=9801)
    parser.add_argument("--name", default="ollama-agent-1")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = create_agent(args.name, args.port, args.model)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
