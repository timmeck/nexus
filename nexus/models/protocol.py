"""Nexus protocol message models — the core of AI-to-AI communication."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VerificationMethod(enum.StrEnum):
    NONE = "none"
    SELF_REPORTED = "self_reported"
    CROSS_CHECK = "cross_check"  # verify against independent agent
    DETERMINISTIC = "deterministic"  # compare against known answer


class ResponseStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


# ── NexusRequest ──────────────────────────────────────────────────────


class NexusRequest(BaseModel):
    """A query from one agent to another (or to the router)."""

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    from_agent: str = Field(..., description="ID of the requesting agent")
    to_agent: str | None = Field(None, description="Target agent ID (None = let router decide)")
    query: str = Field(..., description="The actual question / task")
    capability: str | None = Field(None, description="Required capability name")
    constraints: dict = Field(default_factory=dict)
    budget: float | None = Field(None, description="Max credits willing to spend")
    deadline_ms: int | None = Field(None, description="Max time in ms")
    verification: VerificationMethod = VerificationMethod.NONE
    language: str = Field("en", description="Preferred response language")
    context: dict = Field(default_factory=dict, description="Additional context")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── NexusResponse ─────────────────────────────────────────────────────


class NexusResponse(BaseModel):
    """Response from provider agent back through Nexus."""

    response_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str = Field(..., description="Matching request ID")
    from_agent: str = Field(..., description="ID of the responding agent")
    to_agent: str = Field(..., description="ID of the original requester")
    status: ResponseStatus = ResponseStatus.COMPLETED
    answer: str = Field("", description="The actual response content")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Agent's self-assessed confidence")
    sources: list[str] = Field(default_factory=list)
    cost: float = Field(0.0, description="Actual cost in credits")
    processing_ms: int = Field(0, description="Time spent processing")
    error: str | None = None
    meta: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── NexusCapability ───────────────────────────────────────────────────


class NexusCapability(BaseModel):
    """Standardized capability advertisement."""

    agent_id: str
    capability: str
    description: str = ""
    price_per_request: float = 0.0
    avg_response_ms: int = 5000
    languages: list[str] = Field(default_factory=lambda: ["en"])
    trust_score: float = 0.5
    sla: dict = Field(default_factory=dict)


# ── NexusNegotiation ─────────────────────────────────────────────────


class NexusNegotiation(BaseModel):
    """Agent-to-agent negotiation message."""

    negotiation_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str
    from_agent: str
    to_agent: str
    proposed_price: float | None = None
    proposed_deadline_ms: int | None = None
    accepted: bool | None = None
    counter: dict = Field(default_factory=dict)
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
