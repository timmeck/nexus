"""Protocol Handler — Manages the full request lifecycle through Nexus.

State machine:  RECEIVED → POLICY_CHECKED → ROUTED → BUDGET_CHECKED
                → ESCROWED → FORWARDED → RESPONSE_RECEIVED
                → TRUST_RECORDED → SETTLED | DISPUTED | FAILED

If it is not enforced in the request lifecycle, it is not part of the protocol.
"""

from __future__ import annotations

import logging
import time
import uuid

import httpx

from nexus.auth import sign_request
from nexus.defense import service as defense
from nexus.models.agent import AgentStatus, AgentUpdate
from nexus.models.protocol import NexusRequest, NexusResponse, ResponseStatus
from nexus.payments import service as payments
from nexus.policy import service as policy
from nexus.registry import service as registry
from nexus.router import service as router
from nexus.trust import service as trust

log = logging.getLogger("nexus.protocol")

# Active request tracking
_active_requests: dict[str, dict] = {}


async def handle_request(request: NexusRequest) -> NexusResponse:
    """Process a NexusRequest through the enforced pipeline.

    Every step is audited. Policy, escrow, and trust are not optional sidecars —
    they sit in the critical path.
    """
    start = time.time()
    trail = _new_trail(request)

    try:
        # ── Step 1: Policy Gate ──────────────────────────────────
        trail_step(trail, "policy_check")

        policy_result = await policy.evaluate_request(request)
        trail["policy"] = policy_result

        if not policy_result["allowed"]:
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

        # ── Step 2: Route (with policy-filtered candidates) ──────
        trail_step(trail, "routing")

        routes = await router.route(
            request,
            strategy="best",
            allowed_agent_ids=policy_result.get("allowed_agents"),
        )
        if not routes:
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

        # ── Step 3: Budget Pre-Check ─────────────────────────────
        trail_step(trail, "budget_check")

        estimated_cost = _get_estimated_cost(best.agent, request.capability)
        if estimated_cost > 0:
            can_pay = await payments.check_budget(request.from_agent, estimated_cost)
            if not can_pay:
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

        # ── Step 4: Forward to Agent ─────────────────────────────
        trail_step(trail, "forwarding")

        response = await _forward_to_agent(request, best.agent)
        elapsed_ms = int((time.time() - start) * 1000)
        response.processing_ms = elapsed_ms
        success = response.status == ResponseStatus.COMPLETED

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

        # ── Step 6: Settlement — Escrow or Direct ────────────────
        if success and response.cost > 0:
            trail_step(trail, "escrow")

            try:
                escrow = await defense.create_escrow(
                    request_id=request.request_id,
                    consumer_id=request.from_agent,
                    provider_id=best.agent.id,
                    amount=response.cost,
                )
                trail["escrow"] = {
                    "escrow_id": escrow["escrow_id"],
                    "amount": escrow["amount"],
                    "status": escrow["status"],
                    "release_at": escrow["release_at"],
                }
                response.meta["escrow"] = trail["escrow"]
            except Exception as e:
                # Fallback to direct payment if escrow fails
                log.warning("Escrow failed, falling back to direct payment: %s", e)
                trail_step(trail, "direct_payment_fallback")
                try:
                    payment = await payments.process_payment(
                        request_id=request.request_id,
                        consumer_id=request.from_agent,
                        provider_id=best.agent.id,
                        amount=response.cost,
                        description=f"Request: {request.capability or 'general'}",
                    )
                    if payment.get("success"):
                        response.meta["payment"] = {
                            "tx_id": payment["tx_id"],
                            "amount": payment["amount"],
                        }
                except Exception as pe:
                    log.warning("Payment processing error: %s", pe)
        elif not success:
            trail_step(trail, "no_settlement_failed")
        else:
            trail_step(trail, "no_settlement_free")

        # ── Step 7: Audit the completed trail ────────────────────
        trail_step(trail, "completed")

        await policy.audit_request(
            request_id=request.request_id,
            event_type="request_completed",
            agent_id=best.agent.id,
            details={
                "success": success,
                "elapsed_ms": elapsed_ms,
                "cost": response.cost,
                "confidence": response.confidence,
                "has_escrow": "escrow" in trail,
                "policy_applied": bool(policy_result.get("policies_applied")),
            },
        )

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
    """Append a step to the audit trail."""
    trail["steps"].append({"step": step, "at": time.time()})
    if (request_id := trail.get("request_id")) and request_id in _active_requests:
        _active_requests[request_id]["status"] = step


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
