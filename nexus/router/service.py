"""Routing Layer — Intelligent query routing to best available agent."""

from __future__ import annotations

import logging
import time

from nexus.models.agent import Agent  # noqa: TC001
from nexus.models.protocol import NexusRequest  # noqa: TC001
from nexus.registry import service as registry
from nexus.router.circuit_breaker import get_breaker

log = logging.getLogger("nexus.router")

# ── Agent Health Tracking ────────────────────────────────────────
# Tracks per-agent health metrics for routing decisions.

_agent_health: dict[str, dict] = {}


def _get_health(agent_id: str) -> dict:
    """Return or initialise health record for an agent."""
    if agent_id not in _agent_health:
        _agent_health[agent_id] = {
            "last_success": None,
            "last_failure": None,
            "consecutive_failures": 0,
            "avg_latency_ms": 0.0,
            "_latency_samples": 0,
        }
    return _agent_health[agent_id]


def record_agent_success(agent_id: str, latency_ms: float) -> None:
    """Record a successful response from an agent."""
    h = _get_health(agent_id)
    h["last_success"] = time.time()
    h["consecutive_failures"] = 0
    # Running average of latency
    n = h["_latency_samples"]
    h["avg_latency_ms"] = (h["avg_latency_ms"] * n + latency_ms) / (n + 1)
    h["_latency_samples"] = n + 1
    # Update circuit breaker
    get_breaker(agent_id).record_success()


def record_agent_failure(agent_id: str) -> None:
    """Record a failed response from an agent."""
    h = _get_health(agent_id)
    h["last_failure"] = time.time()
    h["consecutive_failures"] += 1
    # Update circuit breaker
    get_breaker(agent_id).record_failure()


def get_health_factor(agent_id: str) -> float:
    """Compute a 0.0-1.0 health factor for routing score adjustment.

    - 1.0 for healthy agents (no recent failures)
    - Drops by 0.25 per consecutive failure, min 0.1
    """
    h = _get_health(agent_id)
    failures = h["consecutive_failures"]
    if failures == 0:
        return 1.0
    return max(0.1, 1.0 - failures * 0.25)


def get_agent_health(agent_id: str | None = None) -> dict:
    """Return health data for one or all agents, including circuit breaker state."""
    if agent_id:
        health = dict(_get_health(agent_id))
        health["circuit_breaker"] = get_breaker(agent_id).to_dict()
        return health
    result = {}
    for aid, h in _agent_health.items():
        entry = dict(h)
        entry["circuit_breaker"] = get_breaker(aid).to_dict()
        result[aid] = entry
    return result


def reset_agent_health() -> None:
    """Clear all health tracking data (useful for tests)."""
    _agent_health.clear()
    from nexus.router.circuit_breaker import reset_all as reset_breakers

    reset_breakers()


class RouteResult:
    """Result of a routing decision."""

    def __init__(self, agent: Agent, score: float, reason: str):
        self.agent = agent
        self.score = score
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent.id,
            "agent_name": self.agent.name,
            "endpoint": self.agent.endpoint,
            "score": round(self.score, 4),
            "reason": self.reason,
        }


async def route(
    request: NexusRequest,
    strategy: str = "best",
    allowed_agent_ids: list[str] | None = None,
) -> list[RouteResult]:
    """Find the best agent(s) for a request.

    Strategies:
        best     — weighted combination of trust, speed, and price
        cheapest — lowest price first
        fastest  — lowest response time first
        trusted  — highest trust score first

    If allowed_agent_ids is provided, only those agents are considered
    (pre-filtered by the policy layer).
    """
    if request.to_agent:
        agent = await registry.get_agent(request.to_agent)
        if agent:
            # Policy still applies: if direct target is not in allowed set, reject
            if allowed_agent_ids is not None and agent.id not in allowed_agent_ids:
                log.warning("Direct target %s blocked by policy", agent.id)
                return []
            return [RouteResult(agent, 1.0, "direct routing")]
        return []

    # Find candidates by capability
    candidates = await registry.find_by_capability(
        capability=request.capability or "",
        language=request.language,
    )

    if not candidates:
        # Fallback: try all online agents
        candidates = await registry.list_agents(status=registry.AgentStatus.ONLINE)

    if not candidates:
        return []

    # Apply policy filter if provided
    if allowed_agent_ids is not None:
        allowed_set = set(allowed_agent_ids)
        candidates = [c for c in candidates if c.id in allowed_set]
        if not candidates:
            return []

    # Filter out agents with open circuit breakers
    candidates = [c for c in candidates if get_breaker(c.id).allow_request()]
    if not candidates:
        return []

    # Score and rank candidates
    scored = [_score_agent(agent, request, strategy) for agent in candidates]
    scored.sort(key=lambda r: r.score, reverse=True)

    # Apply budget filter
    if request.budget is not None:
        scored = [r for r in scored if _get_price(r.agent, request.capability) <= request.budget]

    log.info(
        "Routed request %s (%s): %d candidates, strategy=%s, winner=%s",
        request.request_id[:8],
        request.capability or "any",
        len(scored),
        strategy,
        scored[0].agent.name if scored else "none",
    )

    return scored


def _score_agent(agent: Agent, request: NexusRequest, strategy: str) -> RouteResult:
    """Score an agent for a given request and strategy.

    The raw score is multiplied by a health_factor (0.1-1.0) that penalises
    agents with recent consecutive failures.
    """
    cap = _find_capability(agent, request.capability)

    trust = agent.trust_score
    speed = 1.0 - min(cap.avg_response_ms / 30000, 1.0) if cap else 0.5
    price = 1.0 - min(cap.price_per_request / 10.0, 1.0) if cap else 0.5
    cap_match = 1.0 if cap else 0.1

    if strategy == "cheapest":
        score = price * 0.7 + trust * 0.2 + speed * 0.1
        reason = f"cheapest: price_score={price:.2f}"
    elif strategy == "fastest":
        score = speed * 0.7 + trust * 0.2 + price * 0.1
        reason = f"fastest: speed_score={speed:.2f}"
    elif strategy == "trusted":
        score = trust * 0.8 + speed * 0.1 + price * 0.1
        reason = f"trusted: trust={trust:.2f}"
    else:  # "best" — balanced
        score = trust * 0.4 + speed * 0.3 + price * 0.2 + cap_match * 0.1
        reason = f"best: trust={trust:.2f} speed={speed:.2f} price={price:.2f}"

    # Apply health factor
    health_factor = get_health_factor(agent.id)
    score *= health_factor
    if health_factor < 1.0:
        reason += f" health={health_factor:.2f}"

    return RouteResult(agent, score, reason)


def _find_capability(agent: Agent, capability_name: str | None):
    """Find a matching capability on an agent."""
    if not capability_name:
        return agent.capabilities[0] if agent.capabilities else None
    for cap in agent.capabilities:
        if cap.name.lower() == capability_name.lower():
            return cap
    return None


def _get_price(agent: Agent, capability_name: str | None) -> float:
    """Get the price for a capability on an agent."""
    cap = _find_capability(agent, capability_name)
    return cap.price_per_request if cap else 0.0
