# Nexus Architecture — Network Topology & Failure Scenarios

## System Overview

```
                              ┌──────────────────────────────────────────────────────────┐
                              │                     NEXUS CORE (:9500)                    │
                              │                                                          │
                              │  ┌───────────┐ ┌─────────┐ ┌──────────┐ ┌───────────┐  │
                              │  │ Discovery  │ │  Trust   │ │ Protocol │ │  Routing   │  │
                              │  │  Registry  │ │ Scoring  │ │ Handler  │ │ 4 Strategy │  │
                              │  │  Search    │ │ Slashing │ │ Request  │ │ best       │  │
                              │  │  Heartbeat │ │ Reports  │ │ Response │ │ cheapest   │  │
                              │  └─────┬──────┘ └────┬─────┘ └────┬─────┘ │ fastest    │  │
                              │        │             │            │       │ trusted    │  │
                              │        └─────────────┼────────────┘       └─────┬──────┘  │
                              │                      │                          │         │
                              │  ┌───────────┐ ┌─────┴─────┐ ┌──────────┐ ┌────┴──────┐  │
                              │  │ Federation │ │ Payments  │ │ Defense  │ │  Policy   │  │
                              │  │  Peers     │ │ Wallets   │ │ Slashing │ │ Locality  │  │
                              │  │  Sync      │ │ Escrow    │ │ Escrow   │ │ Compliance│  │
                              │  │  Remote    │ │ Tx Log    │ │ Challenge│ │ Gateway   │  │
                              │  └────────────┘ └───────────┘ │ Sybil    │ │ Audit     │  │
                              │                               └──────────┘ └───────────┘  │
                              │  ┌────────────────────────────────────────────────────┐   │
                              │  │          WebSocket Real-Time Bus + Schemas          │   │
                              │  └────────────────────────────────────────────────────┘   │
                              └──────────┬────────┬────────┬────────┬────────┬─────────────┘
                                         │        │        │        │        │
               ┌─────────────────────────┼────────┼────────┼────────┼────────┼──────────────────┐
               │                         │        │        │        │        │                  │
               ▼                         ▼        ▼        ▼        ▼        ▼                  ▼
   ┌────────────────┐     ┌──────────────────┐  ┌─────────────┐  ┌──────────────┐   ┌────────────────┐
   │    Cortex       │     │    DocBrain       │  │  Mnemonic    │  │ DeepResearch  │   │   Sentinel     │
   │   :8100         │     │   :8200           │  │  :8300       │  │  :8400        │   │   :8500        │
   │                 │     │                   │  │              │  │               │   │                │
   │ text_generation │     │ document_analysis │  │ memory_mgmt  │  │ deep_research │   │ security_scan  │
   │ code_analysis   │     │ knowledge_retr    │  │ context_track│  │ fact_checking │   │ threat_detect  │
   │                 │     │                   │  │              │  │               │   │                │
   │ POST /nexus/    │     │ POST /nexus/      │  │ POST /nexus/ │  │ POST /nexus/  │   │ POST /nexus/   │
   │      handle     │     │      handle       │  │      handle  │  │      handle   │   │      handle    │
   └────────────────┘     └──────────────────┘  └─────────────┘  └──────────────┘   └────────────────┘

   ┌────────────────┐     ┌──────────────────┐  ┌─────────────────┐
   │  CostControl    │     │   SafetyProxy     │  │   LogAnalyst     │
   │   :8600         │     │   :8700           │  │   :8800          │
   │                 │     │                   │  │                  │
   │ cost_tracking   │     │ injection_detect  │  │ log_analysis     │
   │ budget_mgmt     │     │ pii_detection     │  │ error_explain    │
   │                 │     │                   │  │                  │
   │ POST /nexus/    │     │ POST /nexus/      │  │ POST /nexus/     │
   │      handle     │     │      handle       │  │      handle      │
   └────────────────┘     └──────────────────┘  └─────────────────┘
```

## Federation Topology

```
    ┌─────────────────────┐           ┌─────────────────────┐
    │   NEXUS PRIMARY      │           │  NEXUS SECONDARY     │
    │   :9500              │◄─────────►│  :9600               │
    │                      │  peer     │                      │
    │   8 local agents     │  sync     │   N remote agents    │
    │   wallets + trust    │           │   wallets + trust    │
    │   policies + defense │           │   policies + defense │
    └──────────┬───────────┘           └──────────┬───────────┘
               │                                   │
       ┌───────┴───────┐                   ┌───────┴───────┐
       │ Local Agents   │                   │ Remote Agents  │
       │ (8 products)   │                   │ (discovered    │
       │                │                   │  via sync)     │
       └────────────────┘                   └────────────────┘
```

## Request Flow

```
Consumer                    Nexus Core                     Provider Agent
   │                            │                               │
   │  1. POST /api/protocol/    │                               │
   │     request                │                               │
   │ ──────────────────────────>│                               │
   │                            │                               │
   │                            │  2. Policy check              │
   │                            │     (locality, compliance)    │
   │                            │                               │
   │                            │  3. Route (4 strategies)      │
   │                            │     filter by policy          │
   │                            │                               │
   │                            │  4. HMAC sign request         │
   │                            │                               │
   │                            │  5. POST /nexus/handle        │
   │                            │ ─────────────────────────────>│
   │                            │                               │
   │                            │  6. NexusResponse             │
   │                            │ <─────────────────────────────│
   │                            │                               │
   │                            │  7. Record interaction        │
   │                            │     (trust + payment)         │
   │                            │                               │
   │                            │  8. Escrow payment            │
   │                            │     (held for 60s)            │
   │                            │                               │
   │  9. NexusResponse          │                               │
   │ <──────────────────────────│                               │
   │                            │                               │
   │  [optional: dispute/       │                               │
   │   challenge within 60s]    │                               │
   │                            │                               │
   │                            │  10. Release escrow           │
   │                            │      (auto after 60s)         │
   │                            │                               │
```

## Failure Scenarios

### Agent Down
```
Request → Router → Agent OFFLINE
                     │
                     ├─ Mark agent as OFFLINE
                     ├─ Return NexusResponse(status=failed)
                     └─ Trust penalty applied
```
**Recovery:** Agent sends heartbeat → status back to ONLINE

### Peer Down (Federation)
```
Sync request → Peer UNREACHABLE
                  │
                  ├─ Mark peer status = "offline"
                  ├─ Remote agents still cached locally
                  └─ Retry on next sync cycle
```
**Recovery:** Peer comes back → next sync updates agents

### Payment Failure
```
Request completed → Payment processing
                       │
                       ├─ Insufficient balance → Warning logged, response still returned
                       ├─ Escrow created → Consumer debited
                       ├─ Dispute within 60s → Refund + slash provider
                       └─ No dispute → Auto-release to provider
```

### Sybil Attack
```
Mass registration detected
    │
    ├─ Rate check: >10 agents/hour → flag
    ├─ Maturity check: <5 interactions → untrusted
    ├─ Cluster detection: similar capabilities → flagged
    └─ Slashing: bad output → trust + credits penalty
```

## Layer Summary

| Layer | Module | Tables | Endpoints |
|-------|--------|--------|-----------|
| **Discovery** | `registry/` | `agents` | `/api/registry/*` |
| **Trust** | `trust/` | `interactions` | `/api/trust/*` |
| **Protocol** | `protocol/` | `verifications` | `/api/protocol/*` |
| **Routing** | `router/` | — | `/api/router/*` |
| **Federation** | `federation/` | `peers`, `remote_agents` | `/api/federation/*` |
| **Payments** | `payments/` | `wallets`, `transactions` | `/api/payments/*` |
| **Schemas** | `models/capability_schema` | — | `/api/schemas/*` |
| **Defense** | `defense/` | `escrow`, `challenges`, `slashing_log` | `/api/defense/*` |
| **Policy** | `policy/` | `agent_locality`, `compliance_claims`, `routing_policies`, `gateway_configs`, `audit_log` | `/api/policy/*` |

## Port Map

| Service | Port | Role |
|---------|------|------|
| Nexus Core | 9500 | Protocol layer |
| Nexus Secondary | 9600 | Federation peer |
| Echo Provider | 9501 | Demo agent |
| Consumer | 9502 | Demo agent |
| Cortex | 8100 | Text generation, code analysis |
| DocBrain | 8200 | Document analysis, knowledge retrieval |
| Mnemonic | 8300 | Memory management, context tracking |
| DeepResearch | 8400 | Deep research, fact checking |
| Sentinel | 8500 | Security analysis, threat detection |
| CostControl | 8600 | Cost tracking, budget management |
| SafetyProxy | 8700 | Prompt injection, PII detection |
| LogAnalyst | 8800 | Log analysis, error explanation |
