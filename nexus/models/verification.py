"""Multi-Agent Verification models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VerificationMode(enum.StrEnum):
    """How verification is performed — tied to capability type."""

    TEXT_SIMILARITY = "text_similarity"  # Generic: SequenceMatcher consensus
    STRUCTURED = "structured"  # JSON schema / deterministic field match
    CLAIM_EXTRACTION = "claim_extraction"  # Extract facts + compare critical fields


class Verdict(enum.StrEnum):
    """Verification outcome — determines settlement path."""

    PASS = "pass"
    SUSPICIOUS = "suspicious"  # Claims match but semantic tension detected
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class VerificationRequest(BaseModel):
    """Request to verify a query across multiple agents."""

    query: str = Field(..., description="The query to verify")
    capability: str = Field(..., description="Required capability")
    from_agent: str = Field("verification-system", description="Requester ID")
    min_agents: int = Field(3, ge=2, le=10, description="Minimum agents required")
    language: str = Field("en")
    verification_mode: VerificationMode | None = Field(
        None, description="Override verification mode (auto-detected from capability if None)"
    )
    expected_schema: dict | None = Field(None, description="JSON schema for structured verification")


class AgentAnswer(BaseModel):
    """A single agent's answer in a verification round."""

    agent_id: str
    agent_name: str
    answer: str
    confidence: float
    processing_ms: int
    status: str
    error: str | None = None


class VerificationResult(BaseModel):
    """Result of multi-agent verification."""

    verification_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    query: str
    capability: str
    verification_mode: VerificationMode = VerificationMode.TEXT_SIMILARITY
    verdict: Verdict = Verdict.INCONCLUSIVE
    agents_queried: int
    agents_responded: int
    consensus: bool = Field(description="Whether agents reached consensus")
    consensus_score: float = Field(
        0.0, ge=0.0, le=1.0, description="How much the responses agree (0=total disagreement, 1=perfect consensus)"
    )
    best_answer: str = Field("", description="The answer with highest consensus support")
    answers: list[AgentAnswer] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list, description="Detected contradictions between answers")
    created_at: datetime = Field(default_factory=datetime.utcnow)
