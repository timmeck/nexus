---
name: Adversarial test case
about: Report an agent pattern that escapes verification, or improves coverage
title: "[adversarial] "
labels: adversarial, verification
---

## The attack pattern

<!-- What kind of agent behavior are you testing? Examples: omission, collusion, style mimicry, semantic swap. -->

## Expected verdict

<!-- What Nexus should return: PASS, FAIL, or SUSPICIOUS. -->

## Actual verdict

<!-- What Nexus actually returned. If it escaped (got PASS when it should be FAIL or SUSPICIOUS), this is a verification gap. -->

## Reproducible test

If you can, add a failing test case to `tests/test_red_team.py` and link the PR. A failing test is the fastest path to a fix.

```python
# Example agent setup that produces the escape
```

## Why this matters

<!-- What real-world misuse does this pattern enable? -->
