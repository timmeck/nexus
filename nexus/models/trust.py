"""Trust and reputation models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InteractionRecord(BaseModel):
    """Record of a single agent-to-agent interaction for trust calculation."""

    interaction_id: str
    request_id: str
    consumer_id: str
    provider_id: str
    success: bool
    confidence: float = 0.0
    verified: bool = False
    cost: float = 0.0
    response_ms: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TrustReport(BaseModel):
    """Trust summary for an agent."""

    agent_id: str
    agent_name: str
    trust_score: float
    total_interactions: int
    successful_interactions: int
    success_rate: float
    avg_confidence: float
    avg_response_ms: float
    total_earned: float
