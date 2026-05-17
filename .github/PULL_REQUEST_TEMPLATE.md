## What this changes

<!-- One or two sentences. What problem does this solve? -->

## Layer

- [ ] Outer (api, sdk, agents, docs) — open contributions
- [ ] Core (protocol, defense, trust, payments, policy, verification, auth) — see CONTRIBUTING.md

## Invariant impact

<!-- For Core PRs: which invariants does this touch? List the ones from docs/invariants.md or note "no invariant change". -->

## CAS compliance (core mutations only)

- [ ] All mutations of shared finalizable state use `UPDATE ... WHERE current_status = ?` with rowcount check
- [ ] No SELECT-then-UPDATE for state transitions
- [ ] N/A — not a core mutation

## Tests

- [ ] New tests added for new behavior
- [ ] Existing tests still pass locally (`pytest`)
- [ ] Adversarial / red-team tests still pass (`python red_team_isolated.py`)

## Checklist

- [ ] No new bypass path around the state machine
- [ ] No alternative settlement / dispatch path introduced
- [ ] Escrow exclusivity preserved
- [ ] No secrets, tokens, or credentials in the diff
- [ ] Documentation updated if behavior changed
