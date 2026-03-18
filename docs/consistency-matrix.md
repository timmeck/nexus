# Split-Brain Consistency Matrix

> If two objects can become final independently, their legal and illegal combinations must be explicit.

## Request ↔ Escrow

| Request | Escrow | Legal? | Detection | Repair |
|---------|--------|--------|-----------|--------|
| SETTLED | released | Yes | — | — |
| SETTLED | held | **No** | Reconciler | classify + settle/escalate |
| SETTLED | refunded | **No** | Reconciler | critical mismatch |
| REFUNDED | refunded | Yes | — | — |
| REFUNDED | released | **No** | Reconciler | critical mismatch |
| FAILED | held | **No** | Reconciler | auto-refund orphan |
| FAILED | released | **No** | Reconciler | flag inconsistency |
| FAILED | (none) | Yes | — | — |

## Request ↔ Trust Ledger

| Request | Trust Ledger | Legal? | Detection | Repair |
|---------|-------------|--------|-----------|--------|
| SETTLED | success delta | Yes | — | — |
| FAILED | failure delta | Yes | — | — |
| FAILED | no delta | Partial | integrity check | add missing delta |
| FAILED | success delta | **No** | integrity check | flag/escalate |
| SETTLED | no delta | Partial | integrity check | add missing delta |

## Request ↔ Challenge

| Request | Challenge | Legal? | Detection | Repair |
|---------|-----------|--------|-----------|--------|
| SETTLED | (none) | Yes | — | — |
| SETTLED | pending | **No** | Reconciler | close challenge |
| CHALLENGE_WINDOW | pending | Yes | — | — |
| FAILED | pending | **No** | Reconciler | reject challenge |

## Eligibility ↔ Dispatch

| Eligibility | Dispatch | Legal? | Detection | Repair |
|-------------|----------|--------|-----------|--------|
| eligible | sent | Yes | — | — |
| ineligible | sent | **No** | Pre-dispatch guard | should be impossible |

---

# Critical Edge Crash Table

> If two steps can be separated by a crash, the post-crash state must be classified and recoverable.

| Flow | Step N | Step N+1 | Crash State | Dangerous? | Detection | Repair | Expected |
|------|--------|----------|-------------|------------|-----------|--------|----------|
| Reserve → Escrow | Funds reserved | Escrow created | Reserve without escrow | Medium | Reconciler | Free reserve or create escrow | Consistent |
| Escrow → Dispatch | Escrow created | Dispatch sent | Orphaned escrow | High | Reconciler | Refund + fail | Escrow refunded |
| Dispatch → Response | Dispatch sent | Response saved | Inflight ambiguity | High | Timeout/callback | Reconciler | Classify + recover |
| Response → Verification | Response saved | Verification started | Hanging request | Medium | Reconciler | Retry verification or fail | Resolved |
| Verdict → Settlement | Verdict stored | Escrow finalized | Verdict without finality | High | Reconciler | Settle/refund | Escrow finalized |
| Settlement → Trust | Escrow finalized | Ledger delta written | Finality without accounting | Medium | Integrity check | Add missing delta | Ledger repaired |
| Reconcile → Repair | Class identified | Repair executed | Incomplete repair | Medium | Reconciler re-run | Must be idempotent | Exactly 1 repair |
