---
name: Bug report
about: Report a defect in Nexus core, SDK, or reference agents
title: "[bug] "
labels: bug
---

## What happened

<!-- A clear, factual description of the bug. -->

## Expected behavior

<!-- What you expected to happen, ideally tied to an invariant in docs/invariants.md or a guarantee in README.md. -->

## Reproduction

<!-- Minimal steps to reproduce. A failing test case is the gold standard. -->

```python
# Example: paste the smallest snippet that reproduces the bug
```

## Environment

- Nexus commit SHA:
- Python version:
- OS:
- Are you running with the bundled SQLite or a custom backend?

## Logs / output

<!-- Relevant log lines, error messages, or stack traces. Redact any tokens or credentials. -->

## Is this a security issue?

If the bug allows bypassing an invariant (state machine, escrow exclusivity, trust ledger idempotency, HMAC/replay protection, verification veto), **do not file it here**. See `SECURITY.md` for private disclosure.
