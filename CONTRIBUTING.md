# Contributing to Nexus

Nexus is open source so its guarantees can be **verified** — not just claimed.

## Core Principle

**PRs that weaken invariants will not be merged.**

This is not a suggestion. The protocol's value depends on enforcement, not features.

## What We Accept

### Core (restricted)
These modules have strict review requirements:

- `nexus/protocol/` — State machine, handler, reconciliation
- `nexus/defense/` — Escrow, slashing, challenges
- `nexus/trust/` — Trust ledger, interaction recording
- `nexus/payments/` — Wallets, settlement
- `nexus/policy/` — Policy engine, compliance, locality
- `nexus/verification/` — Verifiers, verdict logic
- `nexus/auth.py` — HMAC, replay protection

**Core PRs must:**
- Not introduce alternative settlement/dispatch paths
- Not bypass the state machine
- Not weaken escrow exclusivity
- Use compare-and-swap (CAS) for any mutation of shared finalizable state
- Include invariant tests for any new guarantees
- Pass the [merge checklist](#merge-checklist)

**CAS Rule:** Any mutation of shared finalizable state must use `UPDATE ... WHERE current_status = ?` with rowcount check, or provide an equivalent atomic guarantee. SELECT-then-UPDATE is forbidden for state transitions.

### Outer Layer (open)
These modules welcome contributions:

- `nexus/api/` — New endpoints, response improvements
- `nexus/sdk.py` — SDK improvements, new integrations
- `agents/` — Demo agents, examples
- `docs/` — Documentation, diagrams
- `static/` — Dashboard UI
- Tests — More adversarial tests are always welcome

## Merge Checklist

Every core PR must answer:

1. Does this make the protocol **harder to bypass**?
2. Is the state machine still the **exclusive authority**?
3. Can settlement still **only happen through escrow**?
4. Are new invariants **tested under failure conditions**?
5. Does the README match what the code actually enforces?

If any answer is unclear: no merge.

## What We Do NOT Accept

- PRs that add direct payment paths bypassing escrow
- PRs that allow state mutations outside the orchestrator
- "Improvements" that weaken terminal state guards
- Feature additions without corresponding invariant tests
- README changes that claim more than the code enforces

## Running Tests

```bash
pip install -r requirements.txt
pytest -v --timeout=10
```

All 152 tests must pass. Lint must be clean:

```bash
ruff check .
ruff format --check .
```

## Code Style

- Python 3.11+, full async/await
- Ruff for linting and formatting (line length: 120)
- No emojis in code or docs

## License

[MIT](LICENSE)
