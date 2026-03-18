# Nexus

**Nexus catches unreliable AI agent outputs before they cost you money.**

[![CI](https://github.com/timmeck/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/timmeck/nexus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-gold.svg)](LICENSE)

---

## The Problem

When Agent A asks Agent B for work, there's no guarantee the result is correct. Agent B can return garbage with 95% confidence, and Agent A pays anyway. No verification, no recourse, no accountability.

**Nexus adds enforcement.** Agent outputs are verified. Payments are held in escrow. Bad actors get slashed. Every step is audited.

## 60-Second Demo

One script shows the entire story:

```bash
git clone https://github.com/timmeck/nexus.git
cd nexus
pip install -r requirements.txt
python demo_cheat.py
```

What happens:
1. A **cheater agent** returns garbage with 95% confidence
2. An **honest agent** returns real analysis
3. Nexus **verification catches the cheater** (26% consensus score)
4. Consumer **disputes the escrow** -- credits returned
5. Cheater gets **slashed** -- trust score drops, credits lost

## Red Team Results

We ran 4 rounds of adversarial testing against the verification system. Every round exposed weaknesses, every weakness was fixed and regression-tested.

| Adversarial Pattern | Verdict | Score | Result |
|---|---|---|---|
| Baseline (2 honest agents) | PASS | 100% | Correct |
| Dumb Liar (obvious garbage, high confidence) | FAIL | 100% | **CAUGHT** |
| Plausible Liar (correct format, wrong facts) | FAIL | 65% | **CAUGHT** |
| Partial Cheater (80% correct, wrong penalties) | FAIL | 82% | **CAUGHT** |
| Style Mimic (exact format, EU->US, euros->dollars) | FAIL | 66% | **CAUGHT** |
| Lazy Agent (generic fluff, no data) | FAIL | 100% | **CAUGHT** |
| Confidence Gamer (99% confidence, vague output) | FAIL | 86% | **CAUGHT** |
| Colluding Pair vs 1 Honest | FAIL | 60% | **CAUGHT** |
| Colluding Pair vs 2 Honest | FAIL | 60% | **CAUGHT** |
| Omission Attack (hides all numbers/dates) | FAIL | 100% | **CAUGHT** |
| Word Numbers ("thirty five million") | FAIL | 65% | **CAUGHT** |
| Coordinated Collusion (varied wrong answers) | FAIL | 74% | **CAUGHT** |

**11/11 adversarial patterns caught. 0 escaped.**

False positive tests (honest agents with different styles): 3/4 pass, 1 edge case at 97%.

Run it yourself: `python red_team_isolated.py`

## Quick Start

```bash
# Start Nexus
python run.py
# Dashboard: http://localhost:9500
# API docs:  http://localhost:9500/docs
```

## 10-Line Integration

Any FastAPI agent joins the network with the standalone SDK (zero nexus dependencies):

```python
from nexus_sdk import NexusAdapter

adapter = NexusAdapter(
    app=app,
    agent_name="my-agent",
    nexus_url="http://localhost:9500",
    endpoint="http://localhost:8000",
    capabilities=[
        {"name": "summarization", "description": "Summarizes text", "price_per_request": 0.01},
    ],
)

@adapter.handle("summarization")
async def handle(query: str, params: dict) -> dict:
    result = await my_summarize(query)
    return {"result": result, "confidence": 0.9, "cost": 0.01}
```

The adapter handles registration, heartbeats (30s), HMAC verification, and request/response serialization automatically.

## How It Works

```
Consumer                         Nexus                        Provider
   |                              |                              |
   |-- request ------------------>|                              |
   |                     [POLICY CHECK]                          |
   |                     [ROUTE TO BEST AGENT]                   |
   |                     [BUDGET CHECK]                          |
   |                     [CREATE ESCROW]                         |
   |                              |-- signed request ----------->|
   |                              |<-- response + confidence ----|
   |                     [RECORD TRUST]                          |
   |                     [SETTLE OR DISPUTE]                     |
   |<-- result + audit trail -----|                              |
```

Every state transition is validated. Invalid jumps raise `InvalidTransitionError`. Terminal states cannot be mutated.

## Verification System

Nexus uses **claim-level verification**, not just string similarity:

1. **Extract** factual claims from each agent's answer (numbers, currencies, dates, jurisdictions, percentages)
2. **Normalize** claims ("35 million" = "35M" = "thirty five million" = 35000000)
3. **Compare** critical fields across agents with weighted scoring
4. **Veto** PASS when critical facts disagree (wrong amounts, wrong jurisdiction, wrong dates)
5. **Detect omissions** when an agent suspiciously hides specific data

This catches the attacks that naive string matching misses: partial cheaters (80% correct, wrong penalties), style mimics (same format, different country/currency), and adversarial formatting (numbers as words).

## Defense Mechanisms

| Mechanism | What it does |
|---|---|
| **Escrow** | Payments held during settlement window. Consumer can dispute. |
| **Slashing** | Bad output + high confidence = trust AND credit penalty |
| **Challenges** | Any agent can dispute another's output |
| **Sybil Detection** | Rate-limited registration, similarity flagging |
| **Replay Protection** | HMAC + timestamp + signature cache (3-layer) |
| **Reconciliation** | Background job catches stuck requests and orphaned escrows |

## Connected Agents

8 agents already integrated via NexusAdapter SDK:

| Agent | Capabilities |
|---|---|
| **Cortex** | text_generation, code_analysis |
| **DocBrain** | document_analysis, knowledge_retrieval |
| **Mnemonic** | memory_management, context_tracking |
| **DeepResearch** | deep_research, fact_checking |
| **Sentinel** | security_analysis, threat_detection |
| **CostControl** | cost_tracking, budget_management |
| **SafetyProxy** | prompt_injection_detection, pii_detection |
| **LogAnalyst** | log_analysis, error_explanation |

## Architecture

9 layers, each in the enforced request path:

| Layer | Purpose |
|---|---|
| Discovery | Agent registry, capability search, heartbeat monitoring |
| Trust | Reputation scoring, interaction tracking |
| Protocol | NexusRequest/NexusResponse lifecycle |
| Routing | Best, cheapest, fastest, or most trusted agent matching |
| Federation | Cross-instance agent registry sync |
| Payments | Credit wallets, pay-per-request |
| Schemas | Formal capability definitions |
| Defense | Slashing, escrow, challenges, sybil detection |
| Policy | Data locality, compliance claims, routing policies |

## What Nexus Does NOT Claim

- Universal truth verification (we measure consistency, not ground truth)
- Perfect resistance to all adversarial strategies
- Production-readiness at scale (yet)
- Coverage for all task types (strongest for structured, factual outputs)

Nexus makes incorrect behavior **harder, more visible, and less profitable** than correct behavior.

## Testing

198 tests + adversarial red team suite:

```bash
# Unit + integration tests
pytest -v               # 198 passed

# Killer demo
python demo_cheat.py    # Cheater caught in 60 seconds

# Full red team suite (12 adversarial + 4 false-positive tests)
python red_team_isolated.py
```

## API Reference

<details>
<summary>Full API (click to expand)</summary>

### Registry
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/registry/agents` | Register agent |
| `GET` | `/api/registry/agents` | List agents |
| `GET` | `/api/registry/agents/{id}` | Get agent |
| `POST` | `/api/registry/agents/{id}/heartbeat` | Heartbeat |
| `GET` | `/api/registry/discover` | Find by capability |

### Protocol
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/protocol/request` | Submit request (enforced lifecycle) |
| `POST` | `/api/protocol/verify` | Multi-agent verification |
| `GET` | `/api/protocol/requests/{id}/events` | Audit trail |

### Trust & Defense
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/trust/report/{id}` | Trust report |
| `POST` | `/api/defense/slash` | Slash agent |
| `GET` | `/api/defense/escrows` | List escrows |
| `POST` | `/api/defense/escrows/{id}/dispute` | Dispute escrow |

### Payments
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/payments/wallets` | List wallets |
| `GET` | `/api/payments/wallets/{id}/balance` | Get balance |
| `POST` | `/api/payments/wallets/{id}/topup` | Add credits |

### System
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/stats` | Network stats |
| `WS` | `/ws/dashboard` | Dashboard WebSocket |

</details>

## Tech Stack

- **Python 3.11+** with full async/await
- **FastAPI** for HTTP + WebSocket API
- **SQLite + aiosqlite** for zero-config persistence
- **Pydantic v2** for data validation
- **httpx** for async agent-to-agent communication

## License

[MIT](LICENSE) -- Tim Mecklenburg

---

Built by [Tim Mecklenburg](https://github.com/timmeck)

[![Star this repo](https://img.shields.io/github/stars/timmeck/nexus?style=social)](https://github.com/timmeck/nexus)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue)](https://paypal.me/tmeck86)
