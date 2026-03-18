# Nexus

**AI-to-AI Protocol Layer** | 9 Layers | 15 Features | 166 Tests

[![CI](https://github.com/timmeck/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/timmeck/nexus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-gold.svg)](LICENSE)

---

Nexus is a protocol for coordinating AI agents under enforceable rules.

Instead of relying on best-effort execution, Nexus enforces:

- **Explicit request lifecycle** — every interaction follows a validated state machine
- **Escrow-based settlement** — no direct payment paths, all outcomes are gated
- **Capability-aware verification** — results are evaluated based on task type
- **Policy and eligibility gates** — only compliant and healthy agents can execute
- **Adversarial invariants** — critical guarantees are enforced and tested under failure conditions

Invalid transitions fail. Duplicate requests are rejected. Settlement cannot bypass escrow. Terminal states cannot be mutated.

Nexus focuses on making agent interactions **reliable under adversarial conditions**, not just functional in ideal ones.

![Nexus Dashboard](docs/dashboard.png)

## The 9 Layers

| Layer | What it does |
|-------|-------------|
| **Discovery** | Agent registry, capability search, heartbeat monitoring |
| **Trust** | Reputation scoring, interaction tracking, trust reports |
| **Protocol** | Standardized NexusRequest/NexusResponse format |
| **Routing** | Best, cheapest, fastest, or most trusted agent matching |
| **Federation** | Multiple Nexus instances sync agent registries across networks |
| **Payments** | Credit wallets, pay-per-request, transaction history |
| **Schemas** | Formal capability definitions (like OpenAPI for agent skills) |
| **Defense** | Slashing, escrow, challenge mechanism, sybil detection |
| **Policy** | Data locality (GDPR), compliance claims, edge gateway integration |

## 15 Features

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Agent Registration** | Register agents with capabilities, pricing, SLA |
| 2 | **Auth per Agent** | API keys + HMAC signing per agent |
| 3 | **Multi-Agent Verification** | Capability-specific verifiers (structured/text), verdict: pass/fail/inconclusive |
| 4 | **Federation** | Peer discovery, agent sync, cross-instance routing |
| 5 | **Micropayments** | Credit wallets, pay-per-request, budgets |
| 6 | **Capability Schema** | Formal skill definitions with JSON Schema |
| 7 | **Slashing Penalties** | Trust + credit loss for bad outputs |
| 8 | **Escrow Settlement** | Payment held in escrow during settlement window (enforced in main path) |
| 9 | **Challenge Mechanism** | Agents can dispute others' outputs |
| 10 | **Sybil Detection** | Rate limiting, similarity flagging, trust farming prevention |
| 11 | **Data Locality** | Region/jurisdiction tagging, GDPR routing |
| 12 | **Compliance Claims** | SHA-256 claim hashes, 10 claim types, verification workflow |
| 13 | **Edge Gateways** | Kong/Tyk/DreamFactory integration configs |
| 14 | **Architecture Docs** | Topology diagrams with failure scenarios |
| 15 | **Protocol Spec** | RFC-style formal specification |

## Quick Start

```bash
git clone https://github.com/timmeck/nexus.git
cd nexus
pip install -r requirements.txt

# Start Nexus
python run.py

# Open dashboard: http://localhost:9500
# API docs: http://localhost:9500/docs
```

### Register an Agent

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
        "price_per_request": 0.01,
        "avg_response_ms": 2000,
        "languages": ["en", "de"]
      }
    ],
    "tags": ["nlp", "text"]
  }'
```

### Send a Request

```bash
curl -X POST http://localhost:9500/api/protocol/request \
  -H "Content-Type: application/json" \
  -d '{
    "from_agent": "consumer-001",
    "query": "Summarize the latest research on LLM agents",
    "capability": "summarization",
    "budget": 0.05
  }'
```

Nexus evaluates policies, finds the best compliant agent, checks budget, creates escrow, forwards the request with HMAC signing, records trust, and settles payment. Every step is tracked in a persistent audit trail.

### Register All 8 Products

```bash
python agents/register_existing.py
```

Registers Cortex, DocBrain, Mnemonic, DeepResearch, Sentinel, CostControl, SafetyProxy, and LogAnalyst.

## Connected Products

| Agent | Port | Capabilities |
|-------|------|-------------|
| **Cortex** | 8100 | text_generation, code_analysis |
| **DocBrain** | 8200 | document_analysis, knowledge_retrieval |
| **Mnemonic** | 8300 | memory_management, context_tracking |
| **DeepResearch** | 8400 | deep_research, fact_checking |
| **Sentinel** | 8500 | security_analysis, threat_detection |
| **CostControl** | 8600 | cost_tracking, budget_management |
| **SafetyProxy** | 8700 | prompt_injection_detection, pii_detection |
| **LogAnalyst** | 8800 | log_analysis, error_explanation |

All products expose a `/nexus/handle` endpoint for direct protocol communication.

## How It Works

```
Consumer Agent                    Nexus                     Provider Agent
      |                            |                            |
      |-- "I need text_analysis" ->|                            |
      |                    [RECEIVED]                            |
      |                    [POLICY_APPROVED]                     |
      |                            |-- finds best agent ------->|
      |                    [ROUTED]                              |
      |                    [BUDGET_CHECKED]                      |
      |                            |-- creates escrow ---------->|
      |                    [FORWARDING]                          |
      |                            |-- forwards signed request ->|
      |                            |<--- response + confidence --|
      |                    [TRUST_RECORDED]                      |
      |                    [ESCROWED]                            |
      |                    [SETTLED]                             |
      |<-- result + audit trail ---|                            |
```

State transitions are validated — illegal jumps (e.g. ROUTED → SETTLED) raise `InvalidTransitionError`.

## What Nexus Does NOT Claim

- Perfect resistance to all adversarial strategies
- Guaranteed correctness of agent outputs
- Full enterprise-grade compliance enforcement
- Production-readiness at scale (yet)

Instead, Nexus makes **incorrect behavior harder, more visible, and less profitable** than correct behavior.

## Adversarial Defense

| Mechanism | How it works |
|-----------|-------------|
| **Slashing** | Agents claiming high confidence but delivering bad output lose trust AND credits |
| **Escrow** | Payment held during settlement window, consumer can dispute. No direct payment paths. |
| **Challenge** | Any agent can dispute another's output for a small fee |
| **Sybil Detection** | Rate-limited registration, similarity flagging, trust farming prevention |
| **Replay Protection** | HMAC + timestamp + signature cache (3-layer) |
| **Reconciliation** | Background job detects stuck requests and orphaned escrows |

## Enterprise Policy

| Policy | What it enforces |
|--------|-----------------|
| **Data Locality** | Route only to agents in specific regions (EU, US, etc.) |
| **Compliance Claims** | Declared compliance claims with verification workflow (GDPR, SOC2, HIPAA) |
| **Edge Gateways** | Pre-built configs for Kong, Tyk, DreamFactory |

## API Reference

### Registry
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/registry/agents` | Register agent |
| `GET` | `/api/registry/agents` | List agents |
| `GET` | `/api/registry/agents/{id}` | Get agent |
| `PATCH` | `/api/registry/agents/{id}` | Update agent |
| `DELETE` | `/api/registry/agents/{id}` | Unregister |
| `POST` | `/api/registry/agents/{id}/heartbeat` | Heartbeat |
| `GET` | `/api/registry/agents/{id}/health` | Full health assessment |
| `GET` | `/api/registry/discover` | Find by capability |

### Protocol
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/protocol/request` | Submit request (enforced lifecycle) |
| `POST` | `/api/protocol/verify` | Multi-agent verification (capability-specific) |
| `GET` | `/api/protocol/requests/{id}/events` | Persistent audit trail |
| `GET` | `/api/protocol/active` | Active requests |

### Trust & Defense
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/trust/report/{id}` | Trust report |
| `GET` | `/api/trust/history/{id}` | Interaction history |
| `GET` | `/api/trust/ledger/{id}` | Trust delta ledger (append-only) |
| `POST` | `/api/defense/slash` | Slash agent |
| `POST` | `/api/defense/challenges` | Challenge output |
| `POST` | `/api/defense/challenges/{id}/resolve` | Resolve challenge |
| `GET` | `/api/defense/escrows` | List escrows |
| `POST` | `/api/defense/escrows/{id}/dispute` | Dispute escrow |
| `GET` | `/api/defense/sybil/clusters` | Sybil analysis |
| `GET` | `/api/defense/sybil/maturity/{id}` | Agent maturity |

### Federation
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/federation/peers` | List peers |
| `POST` | `/api/federation/peers` | Add peer |
| `POST` | `/api/federation/sync/{id}` | Sync with peer |
| `GET` | `/api/federation/agents` | Remote agents |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/payments/wallets` | List wallets |
| `GET` | `/api/payments/wallets/{id}` | Get wallet |
| `POST` | `/api/payments/wallets/{id}/topup` | Add credits |
| `GET` | `/api/payments/transactions/{id}` | Transaction history |
| `GET` | `/api/payments/stats` | Payment stats |

### Policy
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/policy/locality` | Set data locality |
| `GET` | `/api/policy/localities` | List all localities |
| `POST` | `/api/policy/compliance` | Submit compliance claim |
| `GET` | `/api/policy/compliance/{agent_id}` | Agent claims |
| `POST` | `/api/policy/compliance/{claim_id}/verify` | Verify claim |
| `POST` | `/api/policy/routing` | Create routing policy |
| `POST` | `/api/policy/gateways` | Register edge gateway |
| `GET` | `/api/policy/audit` | Audit trail |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/stats` | Full network stats |
| `WS` | `/ws/agent/{id}` | Agent WebSocket |
| `WS` | `/ws/dashboard` | Dashboard WebSocket |

## Comparison

| Feature | Nexus | Google A2A | MCP |
|---------|-------|------------|-----|
| Agent discovery | Registry + capability search | DNS-based | Not included |
| Trust scoring | Automatic per-interaction | Not included | Not included |
| Routing | 4 strategies | Client-side | N/A |
| Payments | Built-in credit system | Not included | Not included |
| Federation | Peer sync + remote routing | Not included | Not included |
| Adversarial defense | Slashing, escrow, challenges, sybil | Not included | Not included |
| Enterprise policy | Data locality, compliance claims, routing policies | Planned | Not included |
| Verification | Capability-specific verifiers | Not included | Not included |
| Request lifecycle | Validated state machine | Not included | Not included |
| Audit trail | Persistent per-request events | Not included | Not included |
| Status | **Enforced lifecycle implementation** | Spec only | Working (tools only) |

## Protocol Spec

### NexusRequest
```json
{
  "request_id": "auto-generated",
  "from_agent": "consumer-id",
  "to_agent": null,
  "query": "The actual question",
  "capability": "required capability",
  "constraints": {"region": "eu"},
  "budget": 0.05,
  "deadline_ms": 5000,
  "verification": "cross_check",
  "language": "en"
}
```

### NexusResponse
```json
{
  "response_id": "auto-generated",
  "request_id": "matching request",
  "from_agent": "provider-id",
  "status": "completed",
  "answer": "The response",
  "confidence": 0.92,
  "sources": ["source1"],
  "cost": 0.02,
  "processing_ms": 340
}
```

## Demo

```bash
# Terminal 1: Nexus
python run.py

# Terminal 2: Provider agent
python agents/provider.py

# Terminal 3: Consumer agent
python agents/consumer.py

# Register all 8 products
python agents/register_existing.py
```

## Docker

```bash
docker compose up -d
```

## Testing

```bash
pytest -v
# 166 passed
```

## Tech Stack

- **Python 3.11+** — full async/await
- **FastAPI** — HTTP + WebSocket API
- **SQLite + aiosqlite** — zero-config persistence
- **Pydantic v2** — data validation
- **httpx** — async agent-to-agent communication

## Support

[![Star this repo](https://img.shields.io/github/stars/timmeck/nexus?style=social)](https://github.com/timmeck/nexus)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue)](https://paypal.me/tmeck86)

## License

[MIT](LICENSE) — Tim Mecklenburg

---

Built by [Tim Mecklenburg](https://github.com/timmeck)
