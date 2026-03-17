"""Tests for the Request State Machine — transition validation."""

from __future__ import annotations

import pytest

from nexus.protocol.state_machine import (
    InvalidTransitionError,
    RequestLifecycle,
    RequestState,
)


def test_initial_state():
    """New lifecycle starts in RECEIVED state."""
    lc = RequestLifecycle("test-1")
    assert lc.state == RequestState.RECEIVED
    assert not lc.is_terminal
    assert not lc.is_success


def test_happy_path():
    """Full success path through all states."""
    lc = RequestLifecycle("test-2")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.BUDGET_CHECKED)
    lc.transition(RequestState.FORWARDING)
    lc.transition(RequestState.RESPONSE_RECEIVED)
    lc.transition(RequestState.TRUST_RECORDED)
    lc.transition(RequestState.ESCROWED)
    lc.transition(RequestState.SETTLED)

    assert lc.state == RequestState.SETTLED
    assert lc.is_terminal
    assert lc.is_success
    assert len(lc.history) == 8


def test_free_request_path():
    """Success path for free requests (no escrow, cost=0)."""
    lc = RequestLifecycle("test-3")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.BUDGET_CHECKED)
    lc.transition(RequestState.FORWARDING)
    lc.transition(RequestState.RESPONSE_RECEIVED)
    lc.transition(RequestState.TRUST_RECORDED)
    lc.transition(RequestState.SETTLED)  # skip escrow for free

    assert lc.state == RequestState.SETTLED
    assert lc.is_success


def test_policy_rejection():
    """Policy rejection is a valid terminal path."""
    lc = RequestLifecycle("test-4")
    lc.transition(RequestState.POLICY_REJECTED)

    assert lc.state == RequestState.POLICY_REJECTED
    assert lc.is_terminal
    assert not lc.is_success


def test_no_route_failure():
    """No route available after policy approval."""
    lc = RequestLifecycle("test-5")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.NO_ROUTE)

    assert lc.is_terminal


def test_funds_insufficient():
    """Budget check fails — terminal state."""
    lc = RequestLifecycle("test-6")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.FUNDS_INSUFFICIENT)

    assert lc.is_terminal


def test_provider_failure():
    """Provider fails to respond — terminal."""
    lc = RequestLifecycle("test-7")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.BUDGET_CHECKED)
    lc.transition(RequestState.FORWARDING)
    lc.transition(RequestState.FAILED)

    assert lc.is_terminal


# ── Illegal transition tests ────────────────────────────────


def test_cannot_skip_policy():
    """Cannot jump from RECEIVED to ROUTED — must pass policy first."""
    lc = RequestLifecycle("test-illegal-1")
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.ROUTED)


def test_cannot_skip_routing():
    """Cannot jump from POLICY_APPROVED to FORWARDING."""
    lc = RequestLifecycle("test-illegal-2")
    lc.transition(RequestState.POLICY_APPROVED)
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.FORWARDING)


def test_cannot_settle_without_trust():
    """Cannot settle directly after forwarding — must record trust first."""
    lc = RequestLifecycle("test-illegal-3")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    lc.transition(RequestState.BUDGET_CHECKED)
    lc.transition(RequestState.FORWARDING)
    lc.transition(RequestState.RESPONSE_RECEIVED)
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.SETTLED)


def test_cannot_transition_from_terminal():
    """Once in terminal state, no further transitions allowed."""
    lc = RequestLifecycle("test-illegal-4")
    lc.transition(RequestState.POLICY_REJECTED)
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.POLICY_APPROVED)


def test_cannot_settle_directly_from_routed():
    """The critical invariant: no shortcut from ROUTED to SETTLED."""
    lc = RequestLifecycle("test-illegal-5")
    lc.transition(RequestState.POLICY_APPROVED)
    lc.transition(RequestState.ROUTED)
    with pytest.raises(InvalidTransitionError):
        lc.transition(RequestState.SETTLED)
