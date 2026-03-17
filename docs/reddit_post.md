# I built the first working AI-to-AI Protocol — agents discover, negotiate, and transact with each other without humans in the loop

**TL;DR:** I built Nexus, an open-source protocol that lets AI agents find each other, negotiate terms, verify responses, and handle micropayments — all without human intervention. Think DNS + HTTPS + payment rails, but for AI agents. 66 tests, fully working, MIT licensed.

**GitHub:** https://github.com/timmeck/nexus

---

## The Problem

Every AI agent framework (LangChain, CrewAI, AutoGen) builds agents that talk to tools. MCP connects AI to external services. But **no protocol exists for AI agents to talk to each other**.

If your coding agent needs legal advice, it can't find a legal agent, negotiate a price, send the query, verify the answer, and pay — all automatically. You have to manually wire up every integration.

Google announced A2A (Agent-to-Agent) as a spec. It's a PDF. No implementation. No working code.

## What I Built

**Nexus** — a working AI-to-AI protocol with 5 layers:

| Layer | What It Does | Like... |
|---|---|---|
| **Discovery** | Agents register capabilities, consumers find them | DNS |
| **Trust** | Reputation scoring after every interaction | Certificate Authority |
| **Protocol** | Standardized request/response format | HTTP |
| **Routing** | Find best/cheapest/fastest agent | BGP |
| **Federation** | Multiple Nexus instances sync agent registries | Email servers |

Plus:
- **Micropayments** — credit system, pay-per-request
- **Multi-Agent Verification** — ask 3 agents, compare answers, score confidence
- **Capability Schema** — formal description of what an agent can do
- **Auth** — per-agent API keys with HMAC signing

## How It Works

```
Consumer Agent                    Nexus                     Provider Agent
      |                            |                            |
      |-- "I need text_analysis" ->|                            |
      |                            |-- finds best agent ------->|
      |                            |-- negotiates terms -------->|
      |                            |-- forwards request -------->|
      |                            |<--- response + confidence --|
      |                            |-- verifies (optional) ----->|
      |                            |-- processes payment ------->|
      |<-- result + sources -------|                            |
      |                            |-- updates trust score ----->|
```

## What's Running Right Now

9 agents registered in my local Nexus network:

- **Cortex** — AI Agent OS (persistent agents, multi-agent workflows)
- **DocBrain** — Document management with OCR + AI chat
- **Mnemonic** — Memory-as-a-service for any AI app
- **DeepResearch** — Autonomous web research with report generation
- **Sentinel** — Security scanner (SQLi, XSS, 16 checks)
- **CostControl** — LLM API cost tracking and budgeting
- **SafetyProxy** — Prompt injection detection, PII filtering
- **LogAnalyst** — AI-powered log analysis and anomaly detection
- **Echo Provider** — Demo agent for testing

All open source. All built in 2 days.

## Why This Matters

Right now, if you want Agent A to use Agent B's capabilities, you hardcode the integration. With Nexus:

1. Agent A says "I need legal analysis"
2. Nexus finds 3 legal agents, compares trust scores and prices
3. Routes to the best one
4. Verifies the response against a second agent
5. Handles payment
6. Updates trust scores

**No hardcoding. No human in the loop. Agents negotiate directly.**

This is how the internet worked for humans (DNS + HTTP + HTTPS + payments). Nexus is the same thing for AI.

## Tech Stack

- Python + FastAPI + SQLite (no heavy dependencies)
- 66 tests, all passing
- Runs locally with Ollama (free, no API keys)
- MIT licensed

## What's Next

- Federation with real remote instances
- Nexus SDK for other languages (TypeScript, Go)
- Agent marketplace (list your agent, set pricing, earn credits)
- Formal protocol spec (RFC-style document)

---

**GitHub:** https://github.com/timmeck/nexus

Happy to answer questions. This is genuinely something that doesn't exist yet — I analyzed 15,576 repos on GitHub to verify that before building it.

Built by Tim Mecklenburg | Built with Claude Code
