# Roadmap

Nexus's Phase 1 (enforcement, verification, defense) is complete: 224 tests, 12/12 adversarial patterns caught, 4/4 meta-agent attacks caught.

The agent-protocol landscape in 2026 changed how Nexus is positioned. **Google A2A is the de-facto transport** (Linux Foundation, 150+ orgs, 5 production SDKs, Signed Agent Cards). Microsoft IATP is the de-facto identity-and-reputation layer. PayCrow / ERC-8004 / Nava cover escrow. None of them verify **whether the agent's answer is factually correct**. That is Nexus's lane.

Phase 2 reorients Nexus from "standalone protocol" to **verification middleware** — a verdict service that runs over A2A, IATP, or standalone.

## Status Legend

- **Done** — shipped on `master`, tested, in the request path
- **Planned** — committed direction, no code yet
- **Considered** — credible idea, not committed

## Phase 1 — Verification Engine (Done)

- Claim-level extraction with SUSPICIOUS verdict for semantic tension
- 12/12 adversarial patterns caught (partial cheater, style mimic, omission, collusion, meaning swap, negation, context shift, others)
- 4/4 meta-agent attacks caught (adversaries that know the verifier)
- 0/4 false positives on stylistically diverse honest agents
- HMAC + timestamp + signature-cache replay protection (3 layers)
- Compare-and-swap pattern enforced via CI guards
- Reconciliation job for stuck requests and orphaned escrows
- 224 tests
- See `README.md` and `docs/invariants.md` for the full surface

## Phase 2 — A2A Integration + Verification Reach (Planned)

The unblocking question is: how does an existing A2A network start using Nexus verdicts?

### A2A bridge (top priority)

- **A2A Agent Card consumer** — Nexus's Discovery layer accepts A2A Agent Cards as input. Agents already registered in A2A become available to Nexus verifiers without re-registration.
- **A2A JSON-RPC adapter** — Nexus exposes `/api/protocol/verify` as a JSON-RPC 2.0 endpoint that an A2A client can call directly. Returns Nexus verdict (PASS / FAIL / SUSPICIOUS) plus claim-level diff.
- **A2A verdict callback** — Nexus emits verdicts back into A2A's response flow so they can be consumed by A2A-native escrow (PayCrow, ERC-8004, Nava). Verdict drives release-or-dispute decision.
- **Reference: A2A + Nexus example** — one end-to-end working flow: agent registered on A2A, query routed via A2A, response verified by Nexus, escrow released or slashed based on the verdict.

### Verification reach

- **External truth anchoring** — closes the only architectural gap left from the red team. Consensus-based verification is structurally blind to shared hallucination (all agents wrong identically). Adding an oracle / citation pass for high-stakes requests would close this.
- **Verifier diversity** — current verifiers are claim-extraction variants. Add a structural / logical verifier and an LLM-judge verifier so disagreement *among verifier classes* becomes a signal.
- **Trust score decay + recovery curve** — reputation should age, and slashed agents need a rehabilitation path. Otherwise the network only loses participants.

### Distribution

- **JS / TS SDK** — Python-only adapter locks out LangChain, CrewAI, Vercel AI SDK. The A2A bridge reduces the urgency (A2A already has 5 SDKs), but a thin JS verdict-client is still useful for native Nexus mode.
- **Verdict-as-a-service reference deployment** — a public Nexus that exposes the verifier as a callable service. Anyone with an A2A agent can submit a verification request without running Nexus themselves.

## Phase 3 — Production Operations (Considered, Not Yet Committed)

Listed for honesty, not queued. Production hardening before there are real users is premature.

- PostgreSQL migration path (SQLite is fine for single-node)
- OpenTelemetry traces, Prometheus metrics, SLO dashboards
- OAuth / mTLS / key rotation beyond HMAC (less urgent with A2A's Signed Agent Cards in front)
- Rate limiting and quotas at the registry edge
- Docker + Helm chart, documented backup/restore
- gRPC transport alongside REST + WebSocket
- Agent versioning (capability hashes, semver)

## Out of Scope

- **Competing with A2A on transport.** A2A won. Nexus runs over it.
- **A blockchain.** Nexus uses an append-only ledger because that's what the invariants require — adding consensus layers would be cargo culting.
- **A hosted SaaS managed by us.** The point is self-hostable, open-source, no vendor lock-in.
- **A general-purpose agent framework.** Nexus is a verdict, not a framework.
- **Identity / reputation / escrow** as primary products. Those are solved by A2A / IATP / PayCrow / Nava. Nexus delegates to them.

## How to Influence the Roadmap

- Open an issue describing where you'd plug Nexus into an existing A2A or agent network — concrete integration friction is the most useful input
- Adversarial test cases — if you can craft an agent pattern that escapes verification, that is the most valuable contribution. PR with a failing test under `tests/test_red_team.py`
- A2A bridge work — pick any of the four sub-items in Phase 2 and open a PR
