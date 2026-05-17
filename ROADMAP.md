# Roadmap

Nexus's Phase 1 (enforcement, verification, defense) is complete: 224 tests, 12/12 adversarial patterns caught, 4/4 meta-agent attacks caught, 9 enforced layers in the request path.

This document tracks what is **not yet built** so external readers can see what is fact vs. plan.

## Status Legend

- **Done** — shipped on `master`, tested, in the request path
- **Planned** — committed direction, no code yet
- **Considered** — credible idea, not committed

## Phase 1 — Core Protocol (Done)

- 9 enforced layers: Discovery, Trust, Protocol, Routing, Federation, Payments, Schemas, Defense, Policy
- Claim-level verification with SUSPICIOUS verdict for semantic tension
- HMAC + timestamp + signature-cache replay protection (3 layers)
- Compare-and-swap pattern enforced via CI guards
- Reconciliation job for stuck requests and orphaned escrows
- 198 → 224 tests (chaos, crash injection, cross-object consistency, claim extraction)
- 8 reference agents on the standalone SDK
- See `README.md` and `docs/invariants.md` for the full surface

## Phase 2 — Distribution & Trust Completeness (Planned)

These are the items that, if closed, move Nexus from "impressive demo" to "thing the industry can adopt."

### Trust completeness

- **External truth anchoring** — closes the only architectural gap left after the red team. Consensus-based verification is structurally blind to shared hallucination (all agents wrong in the same way). Adding an oracle/citation pass for high-stakes requests would close this. Today this is documented in `README.md` under "Known Detection Boundaries" — Phase 2 makes it concrete.
- **Verifier diversity** — current verifiers are claim-extraction variants. Add a structural/logical verifier and an LLM-judge verifier so disagreement among verifier classes becomes a signal.
- **Trust score decay + recovery curve** — reputation should age, and slashed agents need a rehabilitation path. Without one, the network only ever loses participants.

### Distribution

- **JS / TS SDK** — Python-only adapter locks out the largest agent ecosystem (LangChain, CrewAI, Vercel AI SDK). Highest single-step adoption lever.
- **Public testnet** — a hosted Nexus instance anyone can register against with one curl command. Without it, "federated" is a claim, not a demo.
- **Formal protocol spec (versioned)** — RFC-style document plus conformance test suite, so third parties can build compatible servers and clients.
- **Reference third-party agent** — at least one agent on the network shipped by someone other than the maintainer.

## Phase 3 — Production Operations (Considered, Not Yet Committed)

These are listed so the gap is honest, not because they are queued. Production-grade hardening before there are real users is premature optimization.

- PostgreSQL migration path (SQLite is fine for single-node)
- OpenTelemetry traces, Prometheus metrics, SLO dashboards
- OAuth / mTLS / key rotation beyond HMAC
- Rate limiting and quotas at the registry edge
- Docker + Helm chart, documented backup/restore
- Real money rails (Stripe / Lightning) instead of credit-only wallets
- gRPC or GraphQL transport alongside REST + WebSocket
- Provider → Nexus → Sub-provider delegation chains
- SLA enforcement with automatic slashing for breaches
- Compliance claim verification (today policy accepts claims as strings)
- Agent versioning (capability hashes, semver)

## Out of Scope

The following are intentionally **not** on the roadmap:

- A blockchain. Nexus uses an append-only audit trail and credit ledger because that is what the invariants require — adding consensus layers would be cargo culting.
- A hosted SaaS managed by us. The point is self-hostable + federated.
- A general-purpose agent framework. Nexus is the protocol between agents, not a replacement for LangChain / CrewAI / AutoGen.

## How to Influence the Roadmap

- Open an issue describing the gap you hit and the use case behind it
- For trust / verification gaps specifically: open a PR with a failing adversarial test case under `tests/test_red_team.py` — that is the fastest path to a fix
- For SDK contributions, see `CONTRIBUTING.md` for the open vs. core boundary
