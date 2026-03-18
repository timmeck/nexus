# Nexus Integrity Model

Formal invariants that the protocol enforces. Every rule has at least one adversarial test.

## Economic Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| E-1 | **Escrow-only settlement** — no payment path bypasses escrow | `process_payment` deprecated; handler source checked by CI | `test_no_direct_payment_in_handler` |
| E-2 | **Release/Dispute mutual exclusion** — exactly one wins | CAS: `UPDATE WHERE status='held'` + rowcount check | `test_escrow_release_vs_dispute_race` |
| E-3 | **released_amount == reserved_amount** — no amount drift | Escrow stores amount at creation; release reads after CAS | `test_released_amount_equals_reserved_amount` |
| E-4 | **Wallet balance conservation** — `sum(wallets) + sum(held_escrow) = constant - slashing` | All movements are internal SQLite writes in same transaction | `test_wallet_balance_conservation` |
| E-5 | **No double escrow per request** — UNIQUE partial index on `escrow(request_id) WHERE status='held'` | SQLite constraint | `test_no_double_escrow_for_same_request` |
| E-6 | **Budget check prevents dispatch** — consumer can't spend more than balance | `check_budget()` before `BUDGET_CHECKED` state | `test_budget_check_prevents_dispatch` |

## State Machine Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| S-1 | **Terminal states are immutable** — no transitions from SETTLED, FAILED, ERROR, etc. | `TERMINAL_STATES` checked first in `transition()` | `test_state_machine_terminal_blocks_all_mutations` |
| S-2 | **No shortcut to SETTLED** — must pass through FORWARDING → RESPONSE_RECEIVED → TRUST_RECORDED | `ALLOWED_TRANSITIONS` graph enforces DAG | `test_state_machine_blocks_routed_to_settled` |
| S-3 | **No direct state writes** — only `RequestLifecycle.transition()` may change state | Handler source inspected by CI | `test_no_direct_state_writes_in_handler` |

## Idempotency Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| I-1 | **Duplicate requests rejected** — same `request_id` blocked on second submission | `request_events` table checked before processing | `test_duplicate_request_rejected` |
| I-2 | **Trust ledger idempotent** — `UNIQUE(agent_id, request_id)` prevents double deltas | SQLite constraint + `INSERT OR IGNORE` | `test_trust_ledger_idempotent_under_duplicate_callback` |
| I-3 | **Payload swap blocked** — same `request_id` with different content still rejected | Idempotency key is `request_id`, not content hash | `test_payload_swap_attack` |

## Concurrency Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| C-1 | **CAS on all finalizable state** — `UPDATE WHERE status='current'` + rowcount | Escrow release, dispute, challenge resolve all use CAS | `test_no_select_then_update_on_escrow_status` |
| C-2 | **Reconciler idempotent under concurrency** — parallel reconciliation produces exactly 1 repair | CAS in dispute_escrow prevents double-refund | `test_reconciler_double_tap_no_double_effect` |
| C-3 | **Challenge resolution exactly-once** — 10x concurrent → 1 success, 9 CAS errors | `UPDATE WHERE status='pending'` | `test_concurrent_challenge_resolution_exactly_one_wins` |

## Trust Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| T-1 | **Trust bounded** — `MIN_TRUST ≤ trust_score ≤ MAX_TRUST` | `MAX()` / `MIN()` in SQL update | `test_trust_farming_bounded_by_ledger` |
| T-2 | **Trust = initial + sum(deltas)** — no drift between score and ledger | Ledger is append-only; score updated atomically | `test_agent_trust_consistent_with_ledger` |
| T-3 | **Replay farming blocked** — duplicate `request_id` creates 0 additional ledger entries | UNIQUE constraint | `test_trust_farming_bounded_by_ledger` |

## Eligibility Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| R-1 | **Offline agents not routed** — reaper marks offline, router excludes | `status` filter in routing query | `test_stale_agent_not_routed` |
| R-2 | **Pre-dispatch drift check** — agent re-verified before forwarding | `is_eligible_for_routing()` called after routing | `test_agent_ineligible_before_dispatch` |
| R-3 | **Policy rejection absolute** — no forwarding after policy reject | State machine: `POLICY_REJECTED` is terminal | `test_policy_reject_blocks_all_dispatch` |

## Crash Recovery Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| CR-1 | **Orphaned escrow healed** — held escrow + terminal event → auto-refund | Reconciler detects via SQL join, disputes via CAS | `test_crash_after_escrow_create_reconciler_heals` |
| CR-2 | **CAS prevents double-credit after partial crash** — released escrow can't be released again | `UPDATE WHERE status='held'` returns rowcount=0 | `test_crash_after_cas_release_partial_state` |
| CR-3 | **Reconciler retry safe** — partial repair + retry = no double effect | CAS on dispute_escrow | `test_crash_during_reconciliation_idempotent_retry` |
| CR-4 | **Failed forwarding = no economic effect** — no escrow, balance untouched | Escrow only created after `RESPONSE_RECEIVED` | `test_crash_after_forwarding_no_orphaned_escrow` |

## Governance Invariants

| ID | Rule | Enforcement | Test |
|----|------|-------------|------|
| G-1 | **No shadow paths in handler** — handler must not contain direct SQL to escrow/trust/wallet tables | Source inspection CI guard | `test_no_forbidden_patterns_in_handler` |
| G-2 | **No shadow paths in router** — router must not modify trust, escrow, or payments | Source inspection CI guard | `test_no_forbidden_patterns_in_router` |
| G-3 | **Deprecated API warns** — `process_payment()` emits DeprecationWarning | Python warnings module | `test_shadow_path_direct_payment_deprecation` |

## Cross-Object Consistency

| ID | Rule | Detection | Test |
|----|------|-----------|------|
| X-1 | **Escrow without request event** — illegal, detectable | `LEFT JOIN request_events` | `test_escrow_without_request_event_detectable` |
| X-2 | **Trust ledger without interaction** — illegal, detectable | `LEFT JOIN interactions` | `test_trust_ledger_without_interaction_detectable` |
| X-3 | **Trust without escrow** — detectable mismatch (crash indicator) | `LEFT JOIN escrow` | `test_crash_after_trust_before_escrow` |
