"""Tests for the Circuit Breaker pattern."""

from __future__ import annotations

import time

import pytest

from nexus.router.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    get_breaker,
    reset_all,
)


@pytest.fixture(autouse=True)
def _clean_breakers():
    """Reset circuit breakers before each test."""
    reset_all()
    yield
    reset_all()


def test_initial_state():
    """New circuit breaker starts CLOSED."""
    cb = CircuitBreaker("agent-1")
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_stays_closed_on_success():
    """Successes keep the circuit CLOSED."""
    cb = CircuitBreaker("agent-1")
    cb.record_success()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0


def test_opens_after_threshold_failures():
    """Circuit opens after 3 consecutive failures."""
    cb = CircuitBreaker("agent-1", failure_threshold=3)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_success_resets_failure_count():
    """A success resets consecutive failures."""
    cb = CircuitBreaker("agent-1", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.consecutive_failures == 0
    assert cb.state == CircuitState.CLOSED


def test_half_open_after_timeout():
    """Circuit transitions to HALF_OPEN after recovery timeout."""
    cb = CircuitBreaker("agent-1", failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False

    # Simulate timeout passing
    cb.last_failure_time = time.time() - 0.2
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_half_open_success_closes():
    """Successful test request in HALF_OPEN transitions to CLOSED."""
    cb = CircuitBreaker("agent-1", failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    cb.last_failure_time = time.time() - 0.2
    cb.allow_request()  # triggers HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0


def test_half_open_failure_reopens():
    """Failed test request in HALF_OPEN transitions back to OPEN."""
    cb = CircuitBreaker("agent-1", failure_threshold=3, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    cb.last_failure_time = time.time() - 0.2
    cb.allow_request()  # triggers HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_to_dict():
    """Circuit breaker serializes to dict."""
    cb = CircuitBreaker("agent-1")
    d = cb.to_dict()
    assert d["agent_id"] == "agent-1"
    assert d["state"] == "closed"
    assert d["failure_threshold"] == 3
    assert d["recovery_timeout"] == 60


def test_global_breaker_registry():
    """get_breaker returns same instance for same agent_id."""
    b1 = get_breaker("agent-x")
    b2 = get_breaker("agent-x")
    assert b1 is b2

    b3 = get_breaker("agent-y")
    assert b3 is not b1


@pytest.mark.asyncio
async def test_health_endpoint_includes_circuit_state(client):
    """The /health endpoint includes circuit breaker state."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "circuit_breakers" in data


@pytest.mark.asyncio
async def test_router_health_includes_circuit_state(client):
    """The /api/router/health endpoint includes circuit breaker state."""
    from nexus.router.service import record_agent_failure, record_agent_success

    record_agent_success("test-agent", 100)
    resp = await client.get("/api/router/health?agent_id=test-agent")
    assert resp.status_code == 200
    data = resp.json()
    assert "circuit_breaker" in data["health"]
    assert data["health"]["circuit_breaker"]["state"] == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_integration_with_router(client):
    """Circuit breaker blocks routing when agent circuit is open."""
    from nexus.router.service import record_agent_failure

    # Record 3 failures to open the circuit
    record_agent_failure("test-agent")
    record_agent_failure("test-agent")
    record_agent_failure("test-agent")

    breaker = get_breaker("test-agent")
    assert breaker.state == CircuitState.OPEN
    assert breaker.allow_request() is False
