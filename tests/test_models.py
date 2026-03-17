"""Tests for Pydantic models."""

from __future__ import annotations

import pytest

from nexus.models.agent import AgentCreate, Capability
from nexus.models.protocol import NexusRequest, NexusResponse, ResponseStatus, VerificationMethod


class TestNexusRequest:
    """Tests for NexusRequest defaults and validation."""

    def test_defaults(self):
        """NexusRequest fills in sensible defaults."""
        req = NexusRequest(from_agent="agent-a", query="Hello")

        assert req.from_agent == "agent-a"
        assert req.query == "Hello"
        assert req.to_agent is None
        assert req.capability is None
        assert req.constraints == {}
        assert req.budget is None
        assert req.deadline_ms is None
        assert req.verification == VerificationMethod.NONE
        assert req.language == "en"
        assert req.context == {}
        # request_id should be auto-generated
        assert len(req.request_id) > 0
        assert req.created_at is not None

    def test_custom_fields(self):
        """NexusRequest accepts custom values."""
        req = NexusRequest(
            from_agent="agent-a",
            to_agent="agent-b",
            query="Translate this",
            capability="translate",
            budget=5.0,
            deadline_ms=10000,
            verification=VerificationMethod.CROSS_CHECK,
            language="de",
        )
        assert req.to_agent == "agent-b"
        assert req.capability == "translate"
        assert req.budget == 5.0
        assert req.deadline_ms == 10000
        assert req.verification == VerificationMethod.CROSS_CHECK
        assert req.language == "de"


class TestNexusResponse:
    """Tests for NexusResponse validation."""

    def test_valid_response(self):
        """NexusResponse can be constructed with required fields."""
        resp = NexusResponse(
            request_id="req-123",
            from_agent="provider",
            to_agent="consumer",
            status=ResponseStatus.COMPLETED,
            answer="Here is the answer",
            confidence=0.95,
        )
        assert resp.request_id == "req-123"
        assert resp.status == ResponseStatus.COMPLETED
        assert resp.answer == "Here is the answer"
        assert resp.confidence == 0.95
        assert resp.cost == 0.0
        assert resp.sources == []

    def test_confidence_bounds(self):
        """NexusResponse rejects confidence outside [0.0, 1.0]."""
        with pytest.raises(ValueError):
            NexusResponse(
                request_id="req-123",
                from_agent="p",
                to_agent="c",
                confidence=1.5,
            )

        with pytest.raises(ValueError):
            NexusResponse(
                request_id="req-123",
                from_agent="p",
                to_agent="c",
                confidence=-0.1,
            )

    def test_default_status(self):
        """NexusResponse defaults to COMPLETED status."""
        resp = NexusResponse(
            request_id="req-123",
            from_agent="p",
            to_agent="c",
        )
        assert resp.status == ResponseStatus.COMPLETED


class TestAgentCreate:
    """Tests for AgentCreate validation."""

    def test_valid_agent(self):
        """AgentCreate accepts valid payloads."""
        agent = AgentCreate(
            name="my-agent",
            endpoint="http://localhost:8000",
            capabilities=[
                Capability(name="summarize", description="Summarizes text"),
            ],
            tags=["nlp", "text"],
        )
        assert agent.name == "my-agent"
        assert agent.endpoint == "http://localhost:8000"
        assert len(agent.capabilities) == 1
        assert agent.capabilities[0].name == "summarize"
        assert agent.tags == ["nlp", "text"]

    def test_empty_name_rejected(self):
        """AgentCreate rejects an empty name."""
        with pytest.raises(ValueError):
            AgentCreate(name="", endpoint="http://localhost:8000")

    def test_name_too_long(self):
        """AgentCreate rejects names exceeding 128 characters."""
        with pytest.raises(ValueError):
            AgentCreate(name="x" * 129, endpoint="http://localhost:8000")

    def test_defaults(self):
        """AgentCreate fills defaults for optional fields."""
        agent = AgentCreate(name="minimal", endpoint="http://localhost:8000")
        assert agent.description == ""
        assert agent.capabilities == []
        assert agent.tags == []
        assert agent.meta is None

    def test_capability_defaults(self):
        """Capability model fills in sensible defaults."""
        cap = Capability(name="test_cap")
        assert cap.description == ""
        assert cap.input_schema is None
        assert cap.output_schema is None
        assert cap.price_per_request == 0.0
        assert cap.avg_response_ms == 5000
        assert cap.languages == ["en"]
