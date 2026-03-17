"""Nexus SDK — Drop-in integration for any FastAPI agent.

Usage in your product:

    from nexus.sdk import NexusAdapter

    adapter = NexusAdapter(
        app=app,
        agent_name="cortex",
        nexus_url="http://localhost:9500",
        endpoint="http://localhost:8100",
        capabilities=[
            {"name": "text_generation", "description": "Generates text from prompts"},
        ],
    )

    # Register capability handlers
    @adapter.handle("text_generation")
    async def handle_text_gen(query: str, params: dict) -> dict:
        result = await your_existing_function(query)
        return {"result": result, "confidence": 0.9}

    # The adapter automatically:
    # - Adds POST /nexus/handle to your FastAPI app
    # - Registers with Nexus on startup
    # - Sends heartbeats every 30s
    # - Verifies HMAC signatures on incoming requests
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request  # noqa: TC002 (runtime: route registration)
from pydantic import BaseModel, Field

from nexus.auth import verify_signature

log = logging.getLogger("nexus.sdk")


class NexusSDKRequest(BaseModel):
    """Incoming NexusRequest (simplified for SDK consumers)."""

    request_id: str = ""
    from_agent: str = ""
    to_agent: str | None = None
    query: str = ""
    capability: str | None = None
    constraints: dict = Field(default_factory=dict)
    budget: float | None = None
    deadline_ms: int | None = None
    verification: str = "none"
    language: str = "en"
    context: dict = Field(default_factory=dict)
    created_at: str = ""


class NexusSDKResponse(BaseModel):
    """Outgoing NexusResponse (simplified for SDK consumers)."""

    response_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    status: str = "completed"
    answer: str = ""
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)
    cost: float = 0.0
    processing_ms: int = 0
    error: str | None = None
    meta: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# Type alias for handler functions
HandlerFunc = Callable[[str, dict], Coroutine[Any, Any, dict]]


class NexusAdapter:
    """Drop-in Nexus integration for any FastAPI application.

    Adds /nexus/handle endpoint, auto-registers with Nexus, sends heartbeats,
    and verifies HMAC signatures.
    """

    def __init__(
        self,
        app: FastAPI,
        agent_name: str,
        nexus_url: str = "http://localhost:9500",
        endpoint: str | None = None,
        capabilities: list[dict] | None = None,
        tags: list[str] | None = None,
        description: str = "",
        api_key: str | None = None,
        heartbeat_interval: int = 30,
    ):
        self.app = app
        self.agent_name = agent_name
        self.nexus_url = nexus_url.rstrip("/")
        self.endpoint = endpoint or "http://localhost:8000"
        self.capabilities = capabilities or []
        self.tags = tags or []
        self.description = description
        self.api_key = api_key
        self.heartbeat_interval = heartbeat_interval
        self._handlers: dict[str, HandlerFunc] = {}
        self._agent_id: str | None = None
        self._heartbeat_task: asyncio.Task | None = None

        # Register the /nexus/handle endpoint
        self._register_route()

        # Hook into app lifespan
        self._wrap_lifespan()

    def handle(self, capability: str):
        """Decorator to register a capability handler.

        The handler receives (query: str, params: dict) and must return
        a dict with at least {"result": str, "confidence": float}.
        """

        def decorator(func: HandlerFunc):
            self._handlers[capability] = func
            return func

        return decorator

    def _register_route(self):
        """Add POST /nexus/handle to the FastAPI app."""

        adapter = self  # capture self for the closure

        @self.app.post("/nexus/handle")
        async def nexus_handle(request: Request):
            body = await request.body()
            body_str = body.decode()

            # Verify HMAC signature if we have an API key
            if adapter.api_key:
                ts = request.headers.get("X-Nexus-Timestamp", "")
                sig = request.headers.get("X-Nexus-Signature", "")
                if not verify_signature(body_str, adapter.api_key, ts, sig):
                    return NexusSDKResponse(
                        from_agent=adapter.agent_name,
                        status="rejected",
                        error="Invalid HMAC signature",
                    ).model_dump()

            import json

            req_data = json.loads(body_str)
            req = NexusSDKRequest(**req_data)

            start = time.perf_counter_ns()
            handler = adapter._handlers.get(req.capability)

            if handler is None:
                return NexusSDKResponse(
                    request_id=req.request_id,
                    from_agent=adapter.agent_name,
                    to_agent=req.from_agent,
                    status="failed",
                    error=f"Unsupported capability: {req.capability}",
                ).model_dump()

            try:
                params = {**req.constraints, **req.context}
                result = await handler(req.query, params)
                elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000

                return NexusSDKResponse(
                    request_id=req.request_id,
                    from_agent=adapter.agent_name,
                    to_agent=req.from_agent,
                    status="completed",
                    answer=result.get("result", str(result)),
                    confidence=result.get("confidence", 0.8),
                    sources=result.get("sources", []),
                    cost=result.get("cost", 0.0),
                    processing_ms=elapsed_ms,
                    meta=result.get("meta", {}),
                ).model_dump()

            except Exception as e:
                elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
                log.exception("Handler error for capability %s", req.capability)
                return NexusSDKResponse(
                    request_id=req.request_id,
                    from_agent=adapter.agent_name,
                    to_agent=req.from_agent,
                    status="failed",
                    processing_ms=elapsed_ms,
                    error=str(e),
                ).model_dump()

    def _wrap_lifespan(self):
        """Wrap the app's lifespan to add Nexus registration and heartbeat."""
        original_lifespan = self.app.router.lifespan_context

        adapter = self

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def wrapped_lifespan(app):
            # Run original lifespan startup
            if original_lifespan:
                ctx = original_lifespan(app)
                await ctx.__aenter__()

            # Register with Nexus
            await adapter._register_with_nexus()
            adapter._heartbeat_task = asyncio.create_task(adapter._heartbeat_loop())

            yield

            # Cleanup
            if adapter._heartbeat_task:
                adapter._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await adapter._heartbeat_task

            if original_lifespan:
                await ctx.__aexit__(None, None, None)

        self.app.router.lifespan_context = wrapped_lifespan

    async def _register_with_nexus(self):
        """Register this agent with the Nexus registry."""
        payload = {
            "name": self.agent_name,
            "description": self.description,
            "endpoint": self.endpoint,
            "capabilities": self.capabilities,
            "tags": self.tags,
        }

        url = f"{self.nexus_url}/api/registry/agents"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                self._agent_id = data.get("id")
                self.api_key = data.get("api_key", self.api_key)
                log.info(
                    "Registered %s with Nexus (id=%s, key=%s)",
                    self.agent_name,
                    self._agent_id,
                    self.api_key[:12] + "..." if self.api_key else "none",
                )
            except httpx.HTTPError as exc:
                log.error("Nexus registration failed: %s", exc)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to Nexus."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._agent_id:
                continue
            url = f"{self.nexus_url}/api/registry/agents/{self._agent_id}/heartbeat"
            async with httpx.AsyncClient(timeout=5) as client:
                try:
                    resp = await client.post(url)
                    resp.raise_for_status()
                except httpx.HTTPError:
                    pass
