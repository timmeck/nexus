"""Request State Machine — explicit states and validated transitions.

If a transition is not in ALLOWED_TRANSITIONS, it cannot happen.
This is the hard enforcement layer that prevents implicit shortcuts.
"""

from __future__ import annotations

import enum


class RequestState(enum.StrEnum):
    """Every request must be in exactly one of these states."""

    RECEIVED = "received"
    POLICY_APPROVED = "policy_approved"
    POLICY_REJECTED = "policy_rejected"
    ROUTED = "routed"
    BUDGET_CHECKED = "budget_checked"
    FUNDS_INSUFFICIENT = "funds_insufficient"
    FORWARDING = "forwarding"
    RESPONSE_RECEIVED = "response_received"
    TRUST_RECORDED = "trust_recorded"
    ESCROWED = "escrowed"
    SETTLED = "settled"
    NO_ROUTE = "no_route"
    FAILED = "failed"
    ERROR = "error"


# Terminal states — no further transitions allowed
TERMINAL_STATES = frozenset(
    {
        RequestState.POLICY_REJECTED,
        RequestState.FUNDS_INSUFFICIENT,
        RequestState.NO_ROUTE,
        RequestState.SETTLED,
        RequestState.FAILED,
        RequestState.ERROR,
    }
)

# Every allowed transition: {from_state: {to_states}}
ALLOWED_TRANSITIONS: dict[RequestState, frozenset[RequestState]] = {
    RequestState.RECEIVED: frozenset(
        {
            RequestState.POLICY_APPROVED,
            RequestState.POLICY_REJECTED,
            RequestState.ERROR,
        }
    ),
    RequestState.POLICY_APPROVED: frozenset(
        {
            RequestState.ROUTED,
            RequestState.NO_ROUTE,
            RequestState.ERROR,
        }
    ),
    RequestState.ROUTED: frozenset(
        {
            RequestState.BUDGET_CHECKED,
            RequestState.FUNDS_INSUFFICIENT,
            RequestState.ERROR,
        }
    ),
    RequestState.BUDGET_CHECKED: frozenset(
        {
            RequestState.FORWARDING,
            RequestState.ERROR,
        }
    ),
    RequestState.FORWARDING: frozenset(
        {
            RequestState.RESPONSE_RECEIVED,
            RequestState.FAILED,
            RequestState.ERROR,
        }
    ),
    RequestState.RESPONSE_RECEIVED: frozenset(
        {
            RequestState.TRUST_RECORDED,
            RequestState.ERROR,
        }
    ),
    RequestState.TRUST_RECORDED: frozenset(
        {
            RequestState.ESCROWED,
            RequestState.SETTLED,  # free requests (cost=0) or failed responses
            RequestState.FAILED,
            RequestState.ERROR,
        }
    ),
    RequestState.ESCROWED: frozenset(
        {
            RequestState.SETTLED,
            RequestState.FAILED,
            RequestState.ERROR,
        }
    ),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition violates the allowed graph."""

    def __init__(self, from_state: RequestState, to_state: RequestState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Illegal transition: {from_state} → {to_state}")


class RequestLifecycle:
    """Tracks and validates request state transitions.

    Usage:
        lifecycle = RequestLifecycle(request_id)
        lifecycle.transition(RequestState.POLICY_APPROVED)
        lifecycle.transition(RequestState.ROUTED)
        # lifecycle.transition(RequestState.SETTLED)  # raises InvalidTransitionError
    """

    def __init__(self, request_id: str):
        self.request_id = request_id
        self.state = RequestState.RECEIVED
        self.history: list[tuple[RequestState, RequestState]] = []

    def transition(self, to_state: RequestState) -> None:
        """Transition to a new state, raising InvalidTransitionError if not allowed."""
        if self.state in TERMINAL_STATES:
            raise InvalidTransitionError(self.state, to_state)

        allowed = ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if to_state not in allowed:
            raise InvalidTransitionError(self.state, to_state)

        self.history.append((self.state, to_state))
        self.state = to_state

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_success(self) -> bool:
        return self.state == RequestState.SETTLED
