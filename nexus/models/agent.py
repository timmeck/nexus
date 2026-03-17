"""Agent registration models."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class AgentStatus(enum.StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    SUSPECT = "suspect"  # Heartbeat stale but not yet offline


class DeterminismLevel(enum.StrEnum):
    """How deterministic the capability's output is."""

    DETERMINISTIC = "deterministic"  # Same input → same output (math, lookup)
    SEMI_DETERMINISTIC = "semi_deterministic"  # Mostly stable (extraction, classification)
    NON_DETERMINISTIC = "non_deterministic"  # Variable (generation, creative)


class PrivacyTier(enum.StrEnum):
    """Data handling guarantees."""

    PUBLIC = "public"  # No data restrictions
    INTERNAL = "internal"  # No external sharing
    CONFIDENTIAL = "confidential"  # Encrypted, audit-logged
    REGULATED = "regulated"  # GDPR/HIPAA/SOC2 required


class Capability(BaseModel):
    """A single capability an agent offers.

    Rich enough for routing, verification, and policy decisions —
    not just name + price.
    """

    name: str = Field(..., description="Capability identifier, e.g. 'legal_analysis'")
    description: str = Field("", description="Human-readable description")
    input_schema: dict | None = Field(None, description="Expected input JSON schema")
    output_schema: dict | None = Field(None, description="Expected output JSON schema")
    price_per_request: float = Field(0.0, description="Cost in credits per request")
    avg_response_ms: int = Field(5000, description="Average response time in ms")
    languages: list[str] = Field(default_factory=lambda: ["en"], description="Supported languages")
    # ── Rich fields for routing/verification/policy ──────────
    determinism: DeterminismLevel = Field(DeterminismLevel.NON_DETERMINISTIC, description="Output determinism level")
    verification_modes: list[str] = Field(
        default_factory=lambda: ["text_similarity"],
        description="Supported verification modes (text_similarity, structured)",
    )
    max_input_tokens: int | None = Field(None, description="Max input size in tokens")
    max_output_tokens: int | None = Field(None, description="Max output size in tokens")
    structured_output: bool = Field(False, description="Whether agent guarantees JSON output")
    privacy_tier: PrivacyTier = Field(PrivacyTier.PUBLIC, description="Data handling guarantee")
    requires_network: bool = Field(False, description="Whether capability needs external network access")
    sla_p95_ms: int | None = Field(None, description="95th percentile latency in ms")


class AgentCreate(BaseModel):
    """Payload for registering a new agent."""

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("")
    endpoint: str = Field(..., description="Base URL the agent listens on")
    capabilities: list[Capability] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    meta: dict | None = Field(None, description="Arbitrary metadata")


class AgentUpdate(BaseModel):
    """Payload for updating an agent."""

    description: str | None = None
    endpoint: str | None = None
    capabilities: list[Capability] | None = None
    tags: list[str] | None = None
    meta: dict | None = None
    status: AgentStatus | None = None


class Agent(BaseModel):
    """Full agent record."""

    id: str
    name: str
    description: str = ""
    endpoint: str
    capabilities: list[Capability] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    meta: dict | None = None
    trust_score: float = 0.5
    status: AgentStatus = AgentStatus.ONLINE
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: datetime | None = None
    total_interactions: int = 0
    successful_interactions: int = 0
    api_key: str | None = Field(None, description="Agent API key for HMAC auth")
    auth_enabled: bool = Field(False, description="Whether HMAC auth is active")
