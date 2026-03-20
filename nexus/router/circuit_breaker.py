"""Circuit Breaker — Per-agent failure isolation.

States:
    CLOSED    — Normal operation, requests pass through.
    OPEN      — Too many failures, requests blocked for a cooldown period.
    HALF_OPEN — Cooldown expired, one test request allowed.

Transitions:
    CLOSED  → OPEN       after `failure_threshold` consecutive failures.
    OPEN    → HALF_OPEN  after `recovery_timeout` seconds.
    HALF_OPEN → CLOSED   if the test request succeeds.
    HALF_OPEN → OPEN     if the test request fails.
"""

from __future__ import annotations

import enum
import logging
import time

log = logging.getLogger("nexus.circuit_breaker")

# Defaults
FAILURE_THRESHOLD = 3
RECOVERY_TIMEOUT = 60  # seconds


class CircuitState(enum.StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-agent circuit breaker."""

    def __init__(
        self,
        agent_id: str,
        failure_threshold: int = FAILURE_THRESHOLD,
        recovery_timeout: float = RECOVERY_TIMEOUT,
    ):
        self.agent_id = agent_id
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time: float | None = None
        self.last_state_change: float = time.time()

    def allow_request(self) -> bool:
        """Check if a request should be allowed through this circuit."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.recovery_timeout:
                self._transition(CircuitState.HALF_OPEN)
                log.info("Circuit for agent %s: OPEN -> HALF_OPEN (testing)", self.agent_id)
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            # Only one test request allowed in HALF_OPEN; subsequent
            # requests are blocked until the test request completes
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)
            self.consecutive_failures = 0
            log.info("Circuit for agent %s: HALF_OPEN -> CLOSED (recovered)", self.agent_id)
        elif self.state == CircuitState.CLOSED:
            self.consecutive_failures = 0

    def record_failure(self) -> None:
        """Record a failed request."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
            log.warning("Circuit for agent %s: HALF_OPEN -> OPEN (test failed)", self.agent_id)
        elif self.state == CircuitState.CLOSED and self.consecutive_failures >= self.failure_threshold:
            self._transition(CircuitState.OPEN)
            log.warning(
                "Circuit for agent %s: CLOSED -> OPEN after %d failures",
                self.agent_id,
                self.consecutive_failures,
            )

    def to_dict(self) -> dict:
        """Serialize circuit state for API responses."""
        return {
            "agent_id": self.agent_id,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self.last_failure_time,
            "last_state_change": self.last_state_change,
        }

    def _transition(self, new_state: CircuitState) -> None:
        self.state = new_state
        self.last_state_change = time.time()


# ── Global circuit breaker registry ─────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(agent_id: str) -> CircuitBreaker:
    """Get or create a circuit breaker for an agent."""
    if agent_id not in _breakers:
        _breakers[agent_id] = CircuitBreaker(agent_id)
    return _breakers[agent_id]


def get_all_breakers() -> dict[str, CircuitBreaker]:
    """Return all circuit breakers."""
    return dict(_breakers)


def reset_all() -> None:
    """Clear all circuit breakers (useful for tests)."""
    _breakers.clear()
