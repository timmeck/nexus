"""
Register existing agents with the Nexus registry.

Registers Cortex, DocBrain, Mnemonic, DeepResearch, and Sentinel
so they appear in the Nexus discovery layer.

Usage:
    python -m agents.register_existing
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEXUS_URL = "http://localhost:9500"

logger = logging.getLogger("register-existing")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS: list[dict[str, Any]] = [
    {
        "name": "cortex",
        "description": (
            "Core intelligence agent providing text generation and code analysis. "
            "Leverages LLM capabilities for natural language output and static code review."
        ),
        "endpoint": "http://localhost:8100",
        "capabilities": [
            {
                "name": "text_generation",
                "description": "Generates coherent text from prompts — articles, summaries, translations, and more.",
                "price_per_request": 0.02,
                "avg_response_ms": 1500,
                "languages": ["en", "de"],
            },
            {
                "name": "code_analysis",
                "description": "Analyzes source code for quality, complexity, potential bugs, and improvement suggestions.",
                "price_per_request": 0.03,
                "avg_response_ms": 2000,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["llm", "generation", "code", "core"],
    },
    {
        "name": "docbrain",
        "description": (
            "Document intelligence agent specializing in document analysis and knowledge retrieval. "
            "Ingests PDFs, markdown, and structured data for semantic search and Q&A."
        ),
        "endpoint": "http://localhost:8200",
        "capabilities": [
            {
                "name": "document_analysis",
                "description": "Parses and analyzes documents — extracts structure, key entities, and metadata.",
                "price_per_request": 0.02,
                "avg_response_ms": 3000,
                "languages": ["en", "de"],
            },
            {
                "name": "knowledge_retrieval",
                "description": "Retrieves relevant knowledge from an indexed document corpus via semantic search.",
                "price_per_request": 0.01,
                "avg_response_ms": 800,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["documents", "rag", "knowledge", "search"],
    },
    {
        "name": "mnemonic",
        "description": (
            "Memory and context agent that manages persistent memory and tracks conversation context "
            "across sessions and agent interactions."
        ),
        "endpoint": "http://localhost:8300",
        "capabilities": [
            {
                "name": "memory_management",
                "description": "Stores, retrieves, and manages long-term memories and knowledge fragments.",
                "price_per_request": 0.005,
                "avg_response_ms": 200,
                "languages": ["en", "de"],
            },
            {
                "name": "context_tracking",
                "description": "Maintains and retrieves conversation context across multi-turn interactions.",
                "price_per_request": 0.005,
                "avg_response_ms": 150,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["memory", "context", "persistence", "state"],
    },
    {
        "name": "deep-research",
        "description": (
            "Deep research agent capable of multi-step research workflows and rigorous fact-checking. "
            "Synthesizes information from multiple sources into comprehensive reports."
        ),
        "endpoint": "http://localhost:8400",
        "capabilities": [
            {
                "name": "deep_research",
                "description": "Performs multi-step research on a topic — gathers, cross-references, and synthesizes sources.",
                "price_per_request": 0.05,
                "avg_response_ms": 10000,
                "languages": ["en", "de"],
            },
            {
                "name": "fact_checking",
                "description": "Verifies claims against known sources and returns a confidence-scored verdict.",
                "price_per_request": 0.03,
                "avg_response_ms": 5000,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["research", "facts", "verification", "synthesis"],
    },
    {
        "name": "sentinel",
        "description": (
            "Security-focused agent providing security analysis and threat detection. "
            "Scans inputs, outputs, and configurations for vulnerabilities and suspicious patterns."
        ),
        "endpoint": "http://localhost:8500",
        "capabilities": [
            {
                "name": "security_analysis",
                "description": "Analyzes code, configurations, and data for security vulnerabilities and best-practice violations.",
                "price_per_request": 0.02,
                "avg_response_ms": 1000,
                "languages": ["en", "de"],
            },
            {
                "name": "threat_detection",
                "description": "Monitors inputs and traffic patterns for malicious content and anomalous behavior.",
                "price_per_request": 0.02,
                "avg_response_ms": 500,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["security", "threats", "monitoring", "safety"],
    },
    {
        "name": "costcontrol",
        "description": (
            "AI Cost Controller that tracks, budgets, and optimizes LLM API spending. "
            "Monitors token usage per app, enforces budget limits, and provides cost analytics."
        ),
        "endpoint": "http://localhost:8600",
        "capabilities": [
            {
                "name": "cost_tracking",
                "description": "Tracks LLM API costs per app, model, and query in real-time.",
                "price_per_request": 0.001,
                "avg_response_ms": 50,
                "languages": ["en", "de"],
            },
            {
                "name": "budget_management",
                "description": "Manages budgets with alerts and auto-model-downgrade when limits are reached.",
                "price_per_request": 0.001,
                "avg_response_ms": 50,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["cost", "budget", "analytics", "llm", "optimization"],
    },
    {
        "name": "safetyproxy",
        "description": (
            "AI Safety Proxy that sits in front of any LLM API. Blocks prompt injection, "
            "detects PII, filters content, and logs all interactions for compliance."
        ),
        "endpoint": "http://localhost:8700",
        "capabilities": [
            {
                "name": "prompt_injection_detection",
                "description": "Detects and blocks prompt injection attacks in LLM inputs.",
                "price_per_request": 0.005,
                "avg_response_ms": 100,
                "languages": ["en", "de"],
            },
            {
                "name": "pii_detection",
                "description": "Detects and redacts personally identifiable information in text.",
                "price_per_request": 0.005,
                "avg_response_ms": 80,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["safety", "compliance", "pii", "guardrails", "proxy"],
    },
    {
        "name": "loganalyst",
        "description": (
            "AI Log Analyst that ingests application logs, detects anomalies, "
            "explains errors with AI, and suggests fixes. Supports nginx, syslog, and custom formats."
        ),
        "endpoint": "http://localhost:8800",
        "capabilities": [
            {
                "name": "log_analysis",
                "description": "Analyzes log files for patterns, anomalies, and error clusters.",
                "price_per_request": 0.01,
                "avg_response_ms": 2000,
                "languages": ["en", "de"],
            },
            {
                "name": "error_explanation",
                "description": "AI-powered explanation of errors with root cause analysis and fix suggestions.",
                "price_per_request": 0.02,
                "avg_response_ms": 3000,
                "languages": ["en", "de"],
            },
        ],
        "tags": ["logs", "monitoring", "anomaly", "devops", "debugging"],
    },
]

# ---------------------------------------------------------------------------
# Registration logic
# ---------------------------------------------------------------------------


async def register_agent(
    client: httpx.AsyncClient, agent: dict[str, Any]
) -> str | None:
    """Register a single agent. Returns the agent_id on success, None on failure."""
    url = f"{NEXUS_URL}/api/registry/agents"
    try:
        resp = await client.post(url, json=agent)
        resp.raise_for_status()
        data = resp.json()
        agent_id = data.get("agent_id") or data.get("id")
        logger.info("Registered %-15s  id=%s", agent["name"], agent_id)
        return agent_id
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Failed to register %s — HTTP %d: %s",
            agent["name"],
            exc.response.status_code,
            exc.response.text[:200],
        )
    except httpx.HTTPError as exc:
        logger.error("Failed to register %s — %s", agent["name"], exc)
    return None


async def register_all() -> None:
    """Register every agent defined in AGENTS."""
    logger.info("Registering %d existing agents with Nexus at %s", len(AGENTS), NEXUS_URL)

    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(
            *(register_agent(client, agent) for agent in AGENTS)
        )

    succeeded = sum(1 for r in results if r is not None)
    failed = len(results) - succeeded
    logger.info(
        "Registration complete: %d succeeded, %d failed", succeeded, failed
    )
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(register_all())
