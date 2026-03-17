"""Protocol Handler — Manages the full request lifecycle through Nexus.

Uses RequestLifecycle for validated state transitions.
If a transition is not in the allowed graph, it raises InvalidTransitionError.

If it is not enforced in the request lifecycle, it is not part of the protocol.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

import httpx

from nexus.auth import sign_request
from nexus.defense import service as defense
from nexus.models.agent import AgentStatus, AgentUpdate
from nexus.models.protocol import NexusRequest, NexusResponse, ResponseStatus
from nexus.payments import service as payments
from nexus.policy import service as policy
from nexus.protocol.state_machine import RequestLifecycle, RequestState
from nexus.registry import service as registry
from nexus.router import service as router
from nexus.trust import service as trust

log = logging.getLogger("nexus.protocol")

# Active request tracking
_active_requests: dict[str, dict] = {}


async def handle_request(request: NexusRequest) -> NexusResponse:
    """Process a NexusRequest through the enforced pipeline.

    Every step is audited. Policy, escrow, and trust are not optional sidecars —
    they sit in the critical path. State transitions are validated.
    """
    start = time.time()
    lifecycle = RequestLifecycle(request.request_id)
    trail = _new_trail(request)

    try:
        # ── Step 1: Policy Gate ──────────────────────────────────
        trail_step(trail, "policy_check")

        policy_result = await policy.evaluate_request(request)
        trail["policy"] = policy_result

        if not policy_result["allowed"]:
            lifecycle.transition(RequestState.POLICY_REJECTED)
            trail_step(trail, "rejected")
            _cleanup(request.request_id)
            return NexusResponse(
                request_id=request.request_id,
                from_agent="nexus-core",
                to_agent=request.from_agent,
                status=ResponseStatus.REJECTED,
                error=f"Policy rejected: {', '.join(policy_result['reasons'])}",
                meta={"trail": trail},
            )

        lifecycle.transition(RequestState.POLICY_APPROVED)

        # ── Step 2: Route (with policy-filtered candidates) ──────
        trail_step(trail, "routing")

        routes = await router.route(
            request,
            strategy="best",
            allowed_agent_ids=policy_result.get("allowed_agents"),
        )
        if not routes:
            lifecycle.transition(RequestState.NO_ROUTE)
            trail_step(trail, "no_route")
            _cleanup(request.request_id)
            return NexusResponse(
                request_id=request.request_id,
                from_agent="nexus-core",
                to_agent=request.from_agent,
                status=ResponseStatus.FAILED,
                error="No suitable agent found after policy filtering",
                meta={"trail": trail},
            )

        best = routes[0]
        trail["routed_to"] = best.agent.id
        trail["route_score"] = best.score
        lifecycle.transition(RequestState.ROUTED)

        # ── Step 3: Budget Pre-Check ─────────────────────────────
        trail_step(trail, "budget_check")

        estimated_cost = _get_estimated_cost(best.agent, request.capability)
        if estimated_cost > 0:
            can_pay = await payments.check_budget(request.from_agent, estimated_cost)
            if not can_pay:
                lifecycle.transition(RequestState.FUNDS_INSUFFICIENT)
                trail_step(trail, "insufficient_funds")
                _cleanup(request.request_id)
                balance = await payments.get_balance(request.from_agent)
                return NexusResponse(
                    request_id=request.request_id,
                    from_agent="nexus-core",
                    to_agent=request.from_agent,
                    status=ResponseStatus.REJECTED,
                    error=f"Insufficient balance: {balance:.4f} < estimated cost {estimated_cost:.4f}",
                    meta={"trail": trail},
                )

        lifecycle.transition(RequestState.BUDGET_CHECKED)

        # ── Step 4: Forward to Agent ─────────────────────────────
        trail_step(trail, "forwarding")
        lifecycle.transition(RequestState.FORWARDING)

        response = await _forward_to_agent(request, best.agent)
        elapsed_ms = int((time.time() - start) * 1000)
        response.processing_ms = elapsed_ms
        success = response.status == ResponseStatus.COMPLETED

        if not success:
            lifecycle.transition(RequestState.FAILED)
            trail_step(trail, "provider_failed")
            response.meta["trail"] = trail
            _cleanup(request.request_id)

            # Audit the failure
            await _audit_completion(request, trail, best.agent.id, policy_result, success, elapsed_ms, response)
            return response

        lifecycle.transition(RequestState.RESPONSE_RECEIVED)

        # ── Step 5: Record Interaction & Update Trust ────────────
        trail_step(trail, "trust_recording")

        await trust.record_interaction(
            request_id=request.request_id,
            consumer_id=request.from_agent,
            provider_id=best.agent.id,
            success=success,
            confidence=response.confidence,
            cost=response.cost,
            response_ms=elapsed_ms,
        )

        lifecycle.transition(RequestState.TRUST_RECORDED)

        # ── Step 6: Settlement — Escrow or Free ──────────────────
        if response.cost > 0:
            trail_step(trail, "escrow")

            escrow = await defense.create_escrow(
                request_id=request.request_id,
                consumer_id=request.from_agent,
                provider_id=best.agent.id,
                amount=response.cost,
            )
            lifecycle.transition(RequestState.ESCROWED)
            trail["escrow"] = {
                "escrow_id": escrow["escrow_id"],
                "amount": escrow["amount"],
                "status": escrow["status"],
                "release_at": escrow["release_at"],
            }
            response.meta["escrow"] = trail["escrow"]

        # ── Step 7: Mark settled ─────────────────────────────────
        lifecycle.transition(RequestState.SETTLED)
        trail_step(trail, "settled")

        await _audit_completion(request, trail, best.agent.id, policy_result, success, elapsed_ms, response)

        trail["final_state"] = lifecycle.state.value
        trail["transitions"] = len(lifecycle.history)
        response.meta["trail"] = trail
        _cleanup(request.request_id)
        return response

    except Exception as e:
        log.exception("Error handling request %s", request.request_id)
        trail_step(trail, "error")
        trail["error"] = str(e)
        _cleanup(request.request_id)
        return NexusResponse(
            request_id=request.request_id,
            from_agent="nexus-core",
            to_agent=request.from_agent,
            status=ResponseStatus.FAILED,
            error=str(e),
            meta={"trail": trail},
        )


async def _audit_completion(
    request: NexusRequest,
    trail: dict,
    agent_id: str,
    policy_result: dict,
    success: bool,
    elapsed_ms: int,
    response: NexusResponse,
) -> None:
    """Write audit record for request completion."""
    try:
        await policy.audit_request(
            request_id=request.request_id,
            event_type="request_completed",
            agent_id=agent_id,
            details={
                "success": success,
                "elapsed_ms": elapsed_ms,
                "cost": response.cost,
                "confidence": response.confidence,
                "has_escrow": "escrow" in trail,
                "policy_applied": bool(policy_result.get("policies_applied")),
            },
        )
    except Exception as e:
        log.warning("Audit write failed: %s", e)


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


# ── Trail helpers ───────────────────────────────────────────────


def _new_trail(request: NexusRequest) -> dict:
    """Create a new audit trail for a request."""
    trail = {
        "trail_id": uuid.uuid4().hex[:12],
        "request_id": request.request_id,
        "from_agent": request.from_agent,
        "capability": request.capability,
        "steps": [],
        "started_at": time.time(),
    }
    _active_requests[request.request_id] = {
        "request": request.model_dump(mode="json"),
        "status": "received",
        "started_at": trail["started_at"],
    }
    trail_step(trail, "received")
    return trail


def trail_step(trail: dict, step: str) -> None:
    """Append a step to the audit trail and persist to DB."""
    previous = trail["steps"][-1]["step"] if trail["steps"] else ""
    trail["steps"].append({"step": step, "at": time.time()})
    if (request_id := trail.get("request_id")) and request_id in _active_requests:
        _active_requests[request_id]["status"] = step

    # Fire-and-forget persist
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        _task = loop.create_task(_persist_event(trail["request_id"], step, previous))  # noqa: RUF006
    except RuntimeError:
        pass


async def _persist_event(request_id: str, step: str, from_state: str = "") -> None:
    """Write a single audit event to the request_events table (fire-and-forget)."""
    try:
        from nexus.database import get_db

        db = await get_db()
        await db.execute(
            """INSERT INTO request_events
               (event_id, request_id, step, from_state, to_state, actor, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uuid.uuid4().hex,
                request_id,
                step,
                from_state,
                step,
                "system",
                json.dumps({}),
                datetime.now(UTC).isoformat(),
            ),
        )
        await db.commit()
    except Exception:
        log.debug("Failed to persist event %s for request %s", step, request_id)


def _cleanup(request_id: str) -> None:
    """Remove request from active tracking."""
    _active_requests.pop(request_id, None)


def _get_estimated_cost(agent, capability_name: str | None) -> float:
    """Estimate cost from agent's capability pricing."""
    if not capability_name:
        return agent.capabilities[0].price_per_request if agent.capabilities else 0.0
    for cap in agent.capabilities:
        if cap.name.lower() == capability_name.lower():
            return cap.price_per_request
    return 0.0
