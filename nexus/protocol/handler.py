"""Protocol Handler — Manages the full request lifecycle through Nexus."""

from __future__ import annotations

import logging
import time

import httpx

from nexus.auth import sign_request
from nexus.models.agent import AgentStatus, AgentUpdate
from nexus.models.protocol import NexusRequest, NexusResponse, ResponseStatus
from nexus.registry import service as registry
from nexus.router import service as router
from nexus.trust import service as trust

log = logging.getLogger("nexus.protocol")

# Active request tracking
_active_requests: dict[str, dict] = {}


async def handle_request(request: NexusRequest) -> NexusResponse:
    """Process a NexusRequest through the full pipeline:

    1. Route to best agent
    2. Forward request to agent endpoint
    3. Collect response
    4. Record interaction & update trust
    5. Return response
    """
    start = time.time()

    # Track request
    _active_requests[request.request_id] = {
        "request": request.model_dump(mode="json"),
        "status": "routing",
        "started_at": start,
    }

    try:
        # Step 1: Route
        routes = await router.route(request, strategy="best")
        if not routes:
            _cleanup(request.request_id)
            return NexusResponse(
                request_id=request.request_id,
                from_agent="nexus-router",
                to_agent=request.from_agent,
                status=ResponseStatus.FAILED,
                error="No suitable agent found for this request",
            )

        best = routes[0]
        _active_requests[request.request_id]["status"] = "forwarding"
        _active_requests[request.request_id]["routed_to"] = best.agent.id

        # Step 2: Forward to agent
        response = await _forward_to_agent(request, best.agent)

        # Step 3: Record interaction
        elapsed_ms = int((time.time() - start) * 1000)
        response.processing_ms = elapsed_ms
        success = response.status == ResponseStatus.COMPLETED

        await trust.record_interaction(
            request_id=request.request_id,
            consumer_id=request.from_agent,
            provider_id=best.agent.id,
            success=success,
            confidence=response.confidence,
            cost=response.cost,
            response_ms=elapsed_ms,
        )

        _cleanup(request.request_id)
        return response

    except Exception as e:
        log.exception("Error handling request %s", request.request_id)
        _cleanup(request.request_id)
        return NexusResponse(
            request_id=request.request_id,
            from_agent="nexus-router",
            to_agent=request.from_agent,
            status=ResponseStatus.FAILED,
            error=str(e),
        )


async def _forward_to_agent(request: NexusRequest, agent) -> NexusResponse:
    """Forward a request to an agent's endpoint with HMAC signing."""
    url = f"{agent.endpoint.rstrip('/')}/nexus/handle"

    try:
        payload_json = request.model_dump_json()
        headers = {"Content-Type": "application/json"}

        # Sign request if agent has auth enabled
        if getattr(agent, "auth_enabled", False) and getattr(agent, "api_key", None):
            auth_headers = sign_request(payload_json, agent.api_key)
            headers.update(auth_headers)
            log.debug("Signed request for agent %s", agent.name)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                content=payload_json,
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                return NexusResponse(**data)
            else:
                return NexusResponse(
                    request_id=request.request_id,
                    from_agent=agent.id,
                    to_agent=request.from_agent,
                    status=ResponseStatus.FAILED,
                    error=f"Agent returned HTTP {resp.status_code}: {resp.text[:500]}",
                )

    except httpx.TimeoutException:
        return NexusResponse(
            request_id=request.request_id,
            from_agent=agent.id,
            to_agent=request.from_agent,
            status=ResponseStatus.TIMEOUT,
            error="Agent did not respond within timeout",
        )
    except httpx.ConnectError:
        # Mark agent as offline
        await registry.update_agent(
            agent.id,
            AgentUpdate(status=AgentStatus.OFFLINE),
        )
        return NexusResponse(
            request_id=request.request_id,
            from_agent=agent.id,
            to_agent=request.from_agent,
            status=ResponseStatus.FAILED,
            error=f"Could not connect to agent at {agent.endpoint}",
        )


def get_active_requests() -> list[dict]:
    """Get list of currently active requests."""
    return list(_active_requests.values())


def _cleanup(request_id: str) -> None:
    """Remove request from active tracking."""
    _active_requests.pop(request_id, None)
