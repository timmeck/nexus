"""Agent registration models."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class AgentStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class Capability(BaseModel):
    """A single capability an agent offers."""

    name: str = Field(..., description="Capability identifier, e.g. 'legal_analysis'")
    description: str = Field("", description="Human-readable description")
    input_schema: dict | None = Field(None, description="Expected input JSON schema")
    output_schema: dict | None = Field(None, description="Expected output JSON schema")
    price_per_request: float = Field(0.0, description="Cost in credits per request")
    avg_response_ms: int = Field(5000, description="Average response time in ms")
    languages: list[str] = Field(default_factory=lambda: ["en"], description="Supported languages")


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
