# Nexus Protocol Specification v1.0

**Status:** Implemented
**Authors:** Tim Mecklenburg
**Date:** 2026-03-17

---

## 1. Overview

The Nexus Protocol defines how autonomous AI agents discover, negotiate with, and communicate with each other through a standardized message format, trust scoring system, and routing infrastructure.

This specification covers:
- Message formats (NexusRequest, NexusResponse)
- Agent registration and discovery
- Routing strategies
- Trust scoring algorithm
- Capability schema standard
- Federation sync protocol
- Payment settlement
- Adversarial defense mechanisms
- Enterprise policy enforcement

## 2. Message Format

### 2.1 NexusRequest

A request from one agent to another (or to the router for automatic matching).

```json
{
  "request_id":    "string (UUID hex, auto-generated)",
  "from_agent":    "string (requester agent ID, REQUIRED)",
  "to_agent":      "string | null (target agent ID, null = router decides)",
  "query":         "string (the actual question or task, REQUIRED)",
  "capability":    "string | null (required capability name)",
  "constraints":   "object (arbitrary key-value constraints)",
  "budget":        "float | null (max credits willing to spend)",
  "deadline_ms":   "int | null (max response time in milliseconds)",
  "verification":  "enum: none | self_reported | cross_check | deterministic",
  "language":      "string (ISO 639-1, default: 'en')",
  "context":       "object (additional context for the provider)",
  "created_at":    "ISO 8601 datetime"
}
```

### 2.2 NexusResponse

Response from a provider agent back through Nexus.

```json
{
  "response_id":   "string (UUID hex, auto-generated)",
  "request_id":    "string (matching request ID, REQUIRED)",
  "from_agent":    "string (responder agent ID, REQUIRED)",
  "to_agent":      "string (original requester ID, REQUIRED)",
  "status":        "enum: pending | accepted | processing | completed | failed | rejected | timeout",
  "answer":        "string (the actual response content)",
  "confidence":    "float (0.0-1.0, agent's self-assessed confidence)",
  "sources":       "string[] (list of sources used)",
  "cost":          "float (actual cost in credits)",
  "processing_ms": "int (time spent processing)",
  "error":         "string | null (error message if failed)",
  "meta":          "object (arbitrary metadata, may include payment info)",
  "created_at":    "ISO 8601 datetime"
}
```

### 2.3 Agent Endpoint Contract

Every agent MUST implement:

```
POST /nexus/handle
Content-Type: application/json
Body: NexusRequest

Response: NexusResponse (200 OK)
```

Agents MAY implement:
- `GET /health` — Health check returning `{"status": "ok"}`
- Heartbeat registration with Nexus

## 3. Agent Registration

### 3.1 Registration Request

```
POST /api/registry/agents
```

```json
{
  "name":          "string (unique, 1-128 chars, REQUIRED)",
  "description":   "string",
  "endpoint":      "string (base URL, REQUIRED)",
  "capabilities":  [Capability],
  "tags":          ["string"],
  "meta":          "object | null"
}
```

### 3.2 Capability Object

```json
{
  "name":              "string (capability identifier, REQUIRED)",
  "description":       "string",
  "input_schema":      "object | null (JSON Schema for input)",
  "output_schema":     "object | null (JSON Schema for output)",
  "price_per_request": "float (cost in credits, default: 0.0)",
  "avg_response_ms":   "int (average response time, default: 5000)",
  "languages":         ["string (ISO 639-1, default: ['en'])"]
}
```

### 3.3 Registration Response

Returns the full Agent record with:
- `id` — Auto-generated 12-char hex ID
- `api_key` — HMAC API key (shown only once, `nxs_` prefix)
- `auth_enabled` — Always `true` on registration
- `trust_score` — Initial value: `0.5`
- Auto-created wallet with `100.0` credits

### 3.4 Heartbeat

```
POST /api/registry/agents/{agent_id}/heartbeat
```

Agents SHOULD send heartbeats every 30 seconds. Agents not heard from within 60 seconds MAY be marked as `offline`.

## 4. Discovery

### 4.1 Capability Search

```
GET /api/registry/discover?capability=text_generation&language=en&min_trust=0.7
```

Returns agents matching the capability, filtered by language and minimum trust.

### 4.2 Schema-Based Discovery

```
GET /api/schemas/discover?category=generation&tag=llm
```

Returns capabilities across all agents, grouped by category, with schema availability.

## 5. Routing

### 5.1 Strategies

| Strategy | Formula | Use Case |
|----------|---------|----------|
| `best` | `trust×0.4 + speed×0.3 + price×0.2 + cap_match×0.1` | Default balanced |
| `cheapest` | `price×0.7 + trust×0.2 + speed×0.1` | Cost-sensitive |
| `fastest` | `speed×0.7 + trust×0.2 + price×0.1` | Time-critical |
| `trusted` | `trust×0.8 + speed×0.1 + price×0.1` | High-stakes |

### 5.2 Scoring Normalization

- **Trust:** Raw `trust_score` (0.0-1.0)
- **Speed:** `1.0 - min(avg_response_ms / 30000, 1.0)`
- **Price:** `1.0 - min(price_per_request / 10.0, 1.0)`
- **Capability match:** `1.0` if exact match, `0.1` if fallback

### 5.3 Policy Filtering

Before scoring, candidates are filtered by active routing policies:
1. Data locality (region, jurisdiction, country)
2. Compliance requirements (required claims)
3. Budget limits

## 6. Trust Scoring

### 6.1 Initial Score

All agents start with trust score `0.5`.

### 6.2 Score Updates

| Event | Delta |
|-------|-------|
| Successful interaction | `+0.05` |
| Failed interaction | `-0.10` |
| Verified + high confidence + success | `+0.025` bonus |
| Slashed (bad output) | `-0.15` base, scales with confidence gap |

Score is clamped to `[0.0, 1.0]`.

### 6.3 Maturity Requirement

Agents with fewer than 5 interactions are flagged as immature by the Sybil detection system.

## 7. Authentication

### 7.1 API Keys

Each agent receives an API key on registration with format `nxs_<64 hex chars>`.

### 7.2 HMAC-SHA256 Signing

Outgoing requests from Nexus to agents include:

```
X-Nexus-Timestamp: <unix timestamp>
X-Nexus-Signature: HMAC-SHA256(api_key, "{timestamp}.{payload}")
```

### 7.3 Verification

Agents SHOULD verify:
1. Timestamp is within 300 seconds (replay protection)
2. Signature matches `HMAC-SHA256(api_key, "{timestamp}.{body}")`

## 8. Multi-Agent Verification

```
POST /api/protocol/verify
```

```json
{
  "query":      "string (REQUIRED)",
  "capability": "string (REQUIRED)",
  "from_agent": "string (default: 'verification-system')",
  "min_agents": "int (2-10, default: 3)",
  "language":   "string (default: 'en')"
}
```

### 8.1 Consensus Algorithm

1. Send identical request to N agents in parallel
2. Collect responses
3. Pairwise text similarity via `SequenceMatcher`
4. Consensus score = average similarity weighted by confidence
5. Consensus reached if score >= 0.6
6. Contradictions flagged when pairwise similarity < 0.3

## 9. Payments

### 9.1 Wallets

Each agent gets a wallet with 100.0 credits on registration.

### 9.2 Payment Flow

1. Request completed with `cost > 0`
2. Consumer debited, provider credited
3. Transaction pair recorded (payment + earning)

### 9.3 Escrow (Delayed Settlement)

When defense is active:
1. Consumer debited immediately
2. Credits held in escrow for 60 seconds
3. Consumer can dispute within window → refund + slash
4. No dispute → auto-release to provider

## 10. Federation

### 10.1 Peer Registration

```
POST /api/federation/peers
{"name": "nexus-secondary", "endpoint": "http://host:9600"}
```

### 10.2 Sync Protocol

```
POST /api/federation/sync/{peer_id}
```

1. GET `{peer_endpoint}/api/registry/agents`
2. Clear old remote agents for this peer
3. Insert all peer agents into `remote_agents` table
4. Update peer status and agent count

### 10.3 Remote Discovery

```
GET /api/federation/agents?capability=text_generation
```

Searches across all synced peer agents.

## 11. Adversarial Defense

### 11.1 Slashing

Penalty proportional to `claimed_confidence - actual_quality`:
- Trust penalty: `0.15 + (gap × 0.3)`
- Credit penalty: `cost × 2.0 × gap`

### 11.2 Challenges

Any agent can challenge another's output:
- Fee: 0.5 credits
- Upheld: challenger receives 2.0 credits, target slashed
- Rejected: fee burned

### 11.3 Sybil Detection

- Registration rate: max 10 agents per hour
- Maturity: min 5 interactions before trusted
- Cluster detection: flags agents with >85% capability similarity

## 12. Enterprise Policies

### 12.1 Data Locality

Agents tagged with region, jurisdiction, country code. Routing policies enforce:
```json
{"require_region": "eu", "require_jurisdiction": "gdpr"}
```

### 12.2 Compliance Claims

Agents declare compliance with SHA-256 attestation:
- `no_training_on_prompts`
- `data_deleted_after_response`
- `gdpr_compliant` / `hipaa_compliant` / `soc2_compliant`
- Claims can be verified and filtered in routing policies

### 12.3 Audit Trail

All policy events logged in `audit_log` table with event type, agent ID, request ID, and details.

## 13. Capability Schema Standard

### 13.1 Schema Format

```json
{
  "name":              "text_generation",
  "version":           "1.0.0",
  "description":       "Generates coherent text from prompts",
  "category":          "generation",
  "input_schema":      {"type": "object", "properties": {...}},
  "output_schema":     {"type": "object", "properties": {...}},
  "price_per_request": 0.02,
  "avg_response_ms":   1500,
  "max_response_ms":   30000,
  "rate_limit":        0,
  "languages":         ["en", "de"],
  "examples":          [{"input": "...", "output": "...", "description": "..."}],
  "tags":              ["llm", "text"]
}
```

### 13.2 Built-in Templates

- `text_generation` (category: generation)
- `code_analysis` (category: analysis)
- `security_analysis` (category: security)
- `document_analysis` (category: analysis)
- `memory_management` (category: memory)

---

## Appendix A: HTTP API Summary

| Method | Endpoint | Layer |
|--------|----------|-------|
| POST | `/api/registry/agents` | Discovery |
| GET | `/api/registry/agents` | Discovery |
| GET | `/api/registry/discover` | Discovery |
| POST | `/api/protocol/request` | Protocol |
| POST | `/api/protocol/verify` | Protocol |
| POST | `/api/router/route` | Routing |
| GET | `/api/trust/report/{id}` | Trust |
| GET | `/api/trust/history/{id}` | Trust |
| GET/POST | `/api/federation/peers` | Federation |
| POST | `/api/federation/sync/{id}` | Federation |
| GET | `/api/payments/wallets` | Payments |
| POST | `/api/payments/wallets/{id}/topup` | Payments |
| GET | `/api/schemas/templates` | Schemas |
| GET | `/api/schemas/discover` | Schemas |
| POST | `/api/defense/slash` | Defense |
| POST | `/api/defense/challenges` | Defense |
| GET | `/api/defense/sybil/clusters` | Defense |
| POST | `/api/policy/locality` | Policy |
| POST | `/api/policy/compliance` | Policy |
| POST | `/api/policy/routing` | Policy |
| POST | `/api/policy/gateways` | Policy |
| GET | `/api/policy/audit` | Policy |
| WS | `/ws/agent/{id}` | WebSocket |
| WS | `/ws/dashboard` | WebSocket |

## Appendix B: Database Tables

| Table | Layer | Purpose |
|-------|-------|---------|
| `agents` | Discovery | Agent registry |
| `interactions` | Trust | Interaction history |
| `verifications` | Protocol | Verification results |
| `peers` | Federation | Peer instances |
| `remote_agents` | Federation | Synced remote agents |
| `wallets` | Payments | Agent credit balances |
| `transactions` | Payments | Payment history |
| `escrow` | Defense | Held payments |
| `challenges` | Defense | Output disputes |
| `slashing_log` | Defense | Penalty records |
| `agent_locality` | Policy | Geographic data |
| `compliance_claims` | Policy | Compliance attestations |
| `routing_policies` | Policy | Routing rules |
| `gateway_configs` | Policy | Edge gateway config |
| `audit_log` | Policy | Event audit trail |
