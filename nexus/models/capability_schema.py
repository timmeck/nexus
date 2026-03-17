"""Capability Schema Standard — Formal specification for agent capabilities.

Like OpenAPI, but for AI agent skills. Each capability has:
- A name and version
- Input/output JSON schemas
- Pricing, SLA, and language info
- Examples for testing
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityExample(BaseModel):
    """An example input/output pair for a capability."""

    input: str = Field(..., description="Example query")
    output: str = Field(..., description="Expected response")
    description: str = Field("", description="What this example demonstrates")


class CapabilitySchema(BaseModel):
    """Formal schema definition for an agent capability.

    This is the Nexus equivalent of an OpenAPI operation:
    it describes exactly what a capability accepts and returns.
    """

    name: str = Field(..., description="Capability identifier")
    version: str = Field("1.0.0", description="Semantic version")
    description: str = Field("", description="Human-readable description")
    category: str = Field("general", description="Category: generation, analysis, security, memory, research, etc.")

    # JSON Schema for input/output
    input_schema: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The input query"},
            },
            "required": ["query"],
        },
        description="JSON Schema for the expected input",
    )
    output_schema: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "The output result"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["result"],
        },
        description="JSON Schema for the expected output",
    )

    # Pricing and SLA
    price_per_request: float = Field(0.0, ge=0.0, description="Cost in credits")
    avg_response_ms: int = Field(5000, ge=0, description="Average response time")
    max_response_ms: int = Field(30000, ge=0, description="Maximum response time (SLA)")
    rate_limit: int = Field(0, ge=0, description="Max requests per minute (0 = unlimited)")

    # Language support
    languages: list[str] = Field(default_factory=lambda: ["en"])

    # Examples
    examples: list[CapabilityExample] = Field(
        default_factory=list,
        description="Example input/output pairs for testing",
    )

    # Tags for discovery
    tags: list[str] = Field(default_factory=list)


class AgentCapabilitySpec(BaseModel):
    """Full capability specification for an agent — like an OpenAPI doc."""

    agent_name: str
    agent_version: str = "1.0.0"
    description: str = ""
    base_url: str = ""
    capabilities: list[CapabilitySchema] = Field(default_factory=list)


# ── Built-in Schema Templates ────────────────────────────────────

SCHEMA_TEMPLATES: dict[str, CapabilitySchema] = {
    "text_generation": CapabilitySchema(
        name="text_generation",
        version="1.0.0",
        description="Generates coherent text from prompts",
        category="generation",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The prompt or question"},
                "max_tokens": {"type": "integer", "default": 1000},
                "temperature": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.7},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number"},
                "tokens_used": {"type": "integer"},
            },
            "required": ["result"],
        },
        examples=[
            CapabilityExample(
                input="Explain quantum computing in one paragraph",
                output="Quantum computing uses quantum bits (qubits) that can exist in superposition...",
                description="Simple explanation request",
            ),
        ],
        tags=["llm", "text", "generation"],
    ),
    "code_analysis": CapabilitySchema(
        name="code_analysis",
        version="1.0.0",
        description="Analyzes source code for quality, bugs, and improvements",
        category="analysis",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The code to analyze"},
                "language": {"type": "string", "description": "Programming language"},
                "focus": {"type": "string", "enum": ["bugs", "quality", "performance", "security"]},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string", "description": "Analysis report"},
                "issues": {"type": "array", "items": {"type": "object"}},
                "confidence": {"type": "number"},
            },
            "required": ["result"],
        },
        tags=["code", "analysis", "quality"],
    ),
    "security_analysis": CapabilitySchema(
        name="security_analysis",
        version="1.0.0",
        description="Analyzes content for security vulnerabilities",
        category="security",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Content to scan"},
                "scan_type": {"type": "string", "enum": ["full", "quick", "deep"]},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "severity": {"type": "string", "enum": ["none", "low", "medium", "high", "critical"]},
                "vulnerabilities": {"type": "array", "items": {"type": "object"}},
                "confidence": {"type": "number"},
            },
            "required": ["result"],
        },
        tags=["security", "vulnerability", "scan"],
    ),
    "document_analysis": CapabilitySchema(
        name="document_analysis",
        version="1.0.0",
        description="Parses and analyzes documents",
        category="analysis",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Document content or query about it"},
                "format": {"type": "string", "enum": ["text", "markdown", "pdf", "html"]},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
            "required": ["result"],
        },
        tags=["documents", "parsing", "analysis"],
    ),
    "memory_management": CapabilitySchema(
        name="memory_management",
        version="1.0.0",
        description="Stores and retrieves agent memories",
        category="memory",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "action": {"type": "string", "enum": ["store", "search", "delete"]},
                "key": {"type": "string"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "memories": {"type": "array", "items": {"type": "object"}},
                "confidence": {"type": "number"},
            },
            "required": ["result"],
        },
        tags=["memory", "storage", "retrieval"],
    ),
}
