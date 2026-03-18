# Nexus Consistency Matrix & Crash Table

> If two objects can become final independently, their legal and illegal combinations must be explicit.
> If two steps can be separated by a crash, the post-crash state must be classified and recoverable.

---

## Split-Brain Consistency Matrix

### Request ↔ Escrow

| ID | Request | Escrow | Legal? | Severity | Detection | Repair | Idempotent? |
|----|---------|--------|--------|----------|-----------|--------|-------------|
| NSB-001 | SETTLED | released | Yes | — | — | — | — |
| NSB-002 | SETTLED | held | **No** | Critical | Reconciler | classify → release or quarantine | must be |
| NSB-003 | SETTLED | refunded | **No** | Critical | Reconciler | quarantine + manual | n/a |
| NSB-004 | REFUNDED | refunded | Yes | — | — | — | — |
| NSB-005 | REFUNDED | released | **No** | Critical | Reconciler | quarantine + manual | n/a |
| NSB-006 | FAILED | held | Partial | High | Reconciler | refund if safe, else escalate | must be |
| NSB-007 | FAILED | released | **No** | Critical | Reconciler | quarantine + manual | n/a |
| NSB-009 | CHALLENGE_WINDOW | held | Yes | — | — | — | — |

### Request ↔ Trust Ledger

| ID | Request | Trust Ledger | Legal? | Severity | Detection | Repair |
|----|---------|-------------|--------|----------|-----------|--------|
| NSB-011 | FAILED | failure delta | Yes | — | — | — |
| NSB-012 | FAILED | success delta | **No** | High | integrity job | compensating delta / quarantine |
| NSB-013 | SETTLED | success delta | Yes | — | — | — |
| NSB-014 | SETTLED | no delta | Partial | Medium | integrity job | add missing delta |
| NSB-015 | REFUNDED | no negative delta | Partial | Medium | integrity job | add missing delta |

### Request ↔ Challenge

| ID | Request | Challenge | Legal? | Severity | Detection | Repair |
|----|---------|-----------|--------|----------|-----------|--------|
| NSB-008 | SETTLED | pending | **No** | High | Reconciler | close/reject stale challenge |
| NSB-010 | CHALLENGED | Escrow released | **No** | High | Reconciler | classify conflict |

### Request ↔ Verification

| ID | Request | Verification | Legal? | Severity | Detection | Repair |
|----|---------|-------------|--------|----------|-----------|--------|
| NSB-016 | SETTLED | pass | Yes | — | — | — |
| NSB-017 | SETTLED | fail | **No** | Critical | integrity job | quarantine + manual |
| NSB-018 | REFUNDED | fail | Yes | — | — | — |
| NSB-019 | REFUNDED | pass (no challenge) | **No** | High | integrity job | classify mismatch |

### Eligibility ↔ Dispatch

| ID | Eligibility | Dispatch | Legal? | Severity | Detection | Repair |
|----|------------|----------|--------|----------|-----------|--------|
| NSB-020 | eligible | sent | Yes | — | — | — |
| NSB-021 | ineligible | sent | **No** | High | pre-dispatch guard | should be impossible |

### Budget ↔ Escrow

| ID | Budget Reserve | Escrow | Legal? | Severity | Detection | Repair |
|----|---------------|--------|--------|----------|-----------|--------|
| NSB-022 | held | created | Yes | — | — | — |
| NSB-023 | held | missing (timeout) | Partial | Medium | Reconciler | release reserve |

---

## Critical Edge Crash Table

| ID | Flow | Step N | Step N+1 | Crash State | Severity | Detection | Repair | Expected |
|----|------|--------|----------|-------------|----------|-----------|--------|----------|
| NCE-001 | Reserve → Escrow | Funds reserved | Escrow created | Reserve without escrow | High | Reconciler | Free reserve or create escrow | No orphan |
| NCE-002 | Escrow → Dispatch | Escrow created | Dispatch sent | Orphaned escrow | High | Reconciler | Refund + fail | Refunded |
| NCE-003 | Dispatch → Response | Dispatch sent | Response saved | Inflight ambiguity | High | Timeout + callback | Classify + recover | Resolved |
| NCE-004 | Response → Verification | Response saved | Verification started | Hanging request | Medium | Reconciler | Retry or fail | Resolved |
| NCE-005 | Verdict → Settlement | Verdict stored | Escrow finalized | Verdict without finality | **Critical** | Reconciler | Settle/refund per verdict | Consistent |
| NCE-006 | Settlement → Request | Escrow finalized | Request finalized | Escrow final, request not | **Critical** | Integrity job | Align request with escrow | Matched |
| NCE-007 | Request → Trust | Request final | Ledger delta written | Final without accounting | Medium | Integrity job | Write missing delta | Complete |
| NCE-008 | Challenge → Resolve | Challenge pending | Challenge resolved | Pending without outcome | Medium | Reconciler | Retry/expire | Resolved |
| NCE-009 | Challenge → Settlement | Challenge resolved | Refund/release | Decision without escrow action | High | Reconciler | Apply consequence | Matched |
| NCE-010 | Reconcile → Repair | Stuck classified | Repair executed | Incomplete repair | High | Next reconciler run | Re-run (CAS/idempotent) | One repair |
| NCE-011 | Eligibility → Dispatch | Pre-dispatch eligible | Network send | Status drifts | Medium | Audit metric | Abort or accept-with-audit | Deterministic |
| NCE-012 | Replay → Effect | Signature accepted | Effect applied | Replay without persist | High | Replay cache + integrity | Dedupe / reprocess | One effect |

---

## Priority

### P0 (Critical path)
- NSB-002/003/005/007: Request ↔ Escrow final mismatch
- NCE-005/006: Verdict → Settlement → Request consistency
- NCE-010: Reconciler repair idempotency

### P1
- NSB-012/014: Trust ledger completeness
- NCE-007: Missing trust delta after finality
- NCE-011: Eligibility drift at dispatch

### P2
- NSB-023: Budget reserve timeout
- NCE-015: Mature release timing

---

## Design Decisions Required

1. **Final mismatch policy**: Request SETTLED + Escrow refunded → quarantine + manual? Or escrow truth wins?
2. **Missing trust delta**: Auto-repair? Or accept eventual consistency?
3. **Last-millisecond eligibility drift**: Abort hard? Reroute? Proceed with audit?

Each must be a single explicit rule, not a judgment call.

---

## Proof Artifacts (existing)

| Invariant | Proof |
|-----------|-------|
| Escrow unique per request | DB UNIQUE constraint |
| Release/Refund exclusive | CAS (WHERE status='held') + chaos test |
| Trust ledger idempotent | UNIQUE(agent_id, request_id) + INSERT OR IGNORE |
| No direct state writes | CI guard test |
| CAS on all finalizations | CI guard test |
| Terminal states block all | Exhaustive test (all states × all targets) |
