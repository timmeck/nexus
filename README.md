# Nexus

**AI-to-AI Protocol Layer** | Discovery | Trust | Protocol | Routing

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-gold.svg)](LICENSE)

---

Nexus is a standardized protocol layer that enables autonomous AI agents to **discover**, **negotiate with**, and **communicate** with each other. It provides the infrastructure that turns isolated agents into an interoperable network.

Think of it as DNS + HTTP + a reputation system, but for AI agents.

## The Problem

Every AI agent speaks its own language. Agent A can't find Agent B, doesn't know what B offers, has no reason to trust B's output, and no standard way to send a request. Nexus solves all four problems.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        NEXUS CORE                           │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │  Discovery   │  │    Trust    │  │     Protocol     │   │
│  │   Layer      │  │    Layer    │  │      Layer       │   │
│  │             │  │             │  │                  │   │
│  │ • Registry   │  │ • Scoring   │  │ • NexusRequest   │   │
│  │ • Search     │  │ • Tracking  │  │ • NexusResponse  │   │
│  │ • Heartbeat  │  │ • Reports   │  │ • Negotiation    │   │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘   │
│         │                │                   │              │
│         └────────────────┼───────────────────┘              │
│                          │                                  │
│                  ┌───────┴───────┐                          │
│                  │    Routing    │                          │
│                  │    Layer      │                          │
│                  │               │                          │
│                  │ • best        │                          │
│                  │ • cheapest    │                          │
│                  │ • fastest     │                          │
│                  │ • trusted     │                          │
│                  └───────────────┘                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              WebSocket Real-Time Bus                 │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
        ┌───────┐     ┌───────┐     ┌───────┐
        │Agent A│     │Agent B│     │Agent C│
        └───────┘     └───────┘     └───────┘
```

### The Four Layers

| Layer | Purpose | Key Feature |
|-------|---------|-------------|
| **Discovery** | Agent registry and capability search | Agents register themselves, others find them by capability |
| **Trust** | Reputation scoring and interaction tracking | Every interaction updates trust scores automatically |
| **Protocol** | Standardized request/response messages | `NexusRequest` in, `NexusResponse` out, always |
| **Routing** | Intelligent agent matching | Four strategies: best, cheapest, fastest, trusted |

## Quick Start

```bash
# Clone and install
git clone https://github.com/timmeck/nexus.git
cd nexus
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start Nexus
python run.py
```

Nexus is now running at `http://localhost:9500`. Open the dashboard or hit `/docs` for the interactive API.

![Nexus Dashboard](docs/dashboard.png)

### Register Your First Agent

```bash
curl -X POST http://localhost:9500/api/registry/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "endpoint": "http://localhost:8000",
    "capabilities": [
      {
        "name": "summarization",
        "description": "Summarizes text documents",
        "languages": ["en", "de"]
      }
    ]
  }'
```

### Send a Request Through Nexus

```bash
curl -X POST http://localhost:9500/api/protocol/request \
  -H "Content-Type: application/json" \
  -d '{
    "from_agent": "consumer-001",
    "query": "Summarize the latest research on LLM agents",
    "capability": "summarization"
  }'
```

Nexus finds the best-matching agent, forwards the request, tracks the interaction, and updates trust scores.

## API Reference

### Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/registry/agents` | Register a new agent |
| `GET` | `/api/registry/agents` | List agents (filter by status, capability, tag) |
| `GET` | `/api/registry/agents/{id}` | Get agent details |
| `PATCH` | `/api/registry/agents/{id}` | Update agent |
| `DELETE` | `/api/registry/agents/{id}` | Unregister agent |
| `POST` | `/api/registry/agents/{id}/heartbeat` | Send heartbeat |
| `GET` | `/api/registry/discover?capability=...` | Discover agents by capability |

### Protocol

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/protocol/request` | Submit a NexusRequest |
| `GET` | `/api/protocol/active` | List in-flight requests |

### Router

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/router/route?strategy=best` | Find matching agents without executing |

### Trust

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/trust/report/{agent_id}` | Get trust report |
| `GET` | `/api/trust/history/{agent_id}` | Get interaction history |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/stats` | Network statistics |
| `WS` | `/ws/agent/{agent_id}` | Real-time agent WebSocket |
| `WS` | `/ws/dashboard` | Real-time dashboard updates |

## Protocol Specification

### NexusRequest

```json
{
  "request_id": "auto-generated UUID",
  "from_agent": "agent-id",
  "to_agent": "target-id or null (router decides)",
  "query": "The actual question or task",
  "capability": "required capability name",
  "constraints": {},
  "budget": 10.0,
  "deadline_ms": 5000,
  "verification": "none | self_reported | cross_check | deterministic",
  "language": "en",
  "context": {}
}
```

### NexusResponse

```json
{
  "response_id": "auto-generated UUID",
  "request_id": "matching request ID",
  "from_agent": "responder-id",
  "to_agent": "requester-id",
  "status": "completed | failed | rejected | timeout",
  "answer": "The actual response content",
  "confidence": 0.92,
  "sources": ["source1", "source2"],
  "cost": 1.5,
  "processing_ms": 340,
  "error": null,
  "meta": {}
}
```

## Demo

Nexus ships with demo agents to show the protocol in action:

```bash
# Terminal 1 — Nexus core
python run.py

# Terminal 2 — Provider agent (port 9501)
python agents/provider.py

# Terminal 3 — Consumer agent (port 9502)
python agents/consumer.py

# Optional — Register existing agents (Cortex, DocBrain, etc.)
python agents/register_existing.py
```

The provider registers its capabilities with Nexus. The consumer discovers the provider through Nexus and sends requests through the protocol layer. Trust scores update in real time.

## Docker

```bash
# Run the full stack
docker compose up -d

# View logs
docker compose logs -f nexus

# Shut down
docker compose down
```

This starts Nexus on port 9500, the demo provider on 9501, and the demo consumer on 9502.

## Comparison

| Feature | Nexus | Google A2A | Anthropic MCP |
|---------|-------|------------|---------------|
| Agent discovery | Built-in registry + capability search | DNS-based | Not included |
| Trust scoring | Automatic, per-interaction | Not included | Not included |
| Routing strategies | 4 strategies (best/cheapest/fastest/trusted) | Client-side | N/A |
| Message negotiation | Built-in | Not included | Not included |
| Real-time updates | WebSocket bus | Streaming | Stdio/SSE |
| Verification | 4 methods including cross-check | Not included | Not included |
| Focus | Agent-to-agent communication | Agent-to-agent tasks | Tool access for LLMs |

Nexus is not a replacement for A2A or MCP. It operates at a different layer: while MCP connects models to tools and A2A defines task delegation, Nexus provides the network infrastructure that lets agents find each other, build trust, and communicate through a standardized protocol.

## Tech Stack

- **Python 3.11+** with full async/await
- **FastAPI** for the HTTP and WebSocket API
- **SQLite + aiosqlite** for zero-config persistence
- **Pydantic v2** for data validation
- **httpx** for async agent-to-agent HTTP

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

```bash
# Dev setup
pip install -r requirements.txt
pip install ruff

# Lint
ruff check .

# Test
pytest -v
```

## License

[MIT](LICENSE) -- Tim Mecklenburg

---

Built by [Tim Mecklenburg](https://github.com/timmeck)
