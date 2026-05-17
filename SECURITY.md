# Security Policy

Nexus is a protocol layer that handles agent authentication, payments, and trust scoring. Vulnerabilities in this code path can directly cause credit loss, reputation manipulation, or bypass of the verification system. We take all reports seriously.

## Reporting a Vulnerability

**Do not open a public issue for security problems.**

Send a report to **tim@timmeck.dev** with:

- A description of the vulnerability and its impact
- Steps to reproduce, ideally with a minimal proof-of-concept
- Affected version (commit SHA or tag)
- Whether you have disclosed this to anyone else

You will receive an acknowledgement within 72 hours. We aim to confirm or refute the report within 7 days and ship a fix within 30 days for confirmed high/critical issues.

## Coordinated Disclosure

We follow a 90-day disclosure timeline by default:

1. **Day 0** — Report received, acknowledged within 72 hours.
2. **Day 1–30** — Triage, reproduction, fix development.
3. **Day 30–90** — Patch released. You are credited (unless you prefer to remain anonymous).
4. **Day 90** — Public advisory published, regardless of patch status.

If a vulnerability is being actively exploited in the wild, we will accelerate disclosure. If you need an extension to coordinate with downstream users, contact us before day 90.

## Scope

**In scope:**

- `nexus/` — protocol handler, state machine, escrow, slashing, trust ledger, auth, verification, policy, federation
- `nexus_sdk.py` (standalone SDK) — HMAC signing, replay protection
- API endpoints under `/api/protocol`, `/api/defense`, `/api/payments`, `/api/trust`, `/api/registry`

**Out of scope:**

- Demo and reference agents under `agents/` — these are illustrative, not production
- Third-party dependencies — report upstream first, then notify us if Nexus is impacted
- Denial-of-service via unbounded local resource consumption that requires authenticated cooperation
- Social engineering, physical attacks, or attacks requiring privileged local access

## What Counts as a Security Issue

Nexus's value depends on its invariants being enforced. The following are always in scope:

- **State machine bypass** — invalid transitions, terminal-state mutation
- **Escrow exclusivity violations** — payment paths that skip escrow, double-settlement
- **Trust ledger corruption** — non-idempotent updates, replay of trust mutations
- **CAS bypass** — race conditions in shared finalizable state (see `CONTRIBUTING.md` for the CAS rule)
- **HMAC / replay protection bypass** — signature forgery, timestamp manipulation, signature-cache evasion
- **Verification bypass** — adversarial agent patterns that achieve PASS verdict despite divergent claims
- **Sybil / federation poisoning** — registry-side abuse, cross-instance trust manipulation

If you find something that breaks an invariant listed in `docs/invariants.md` or the consistency matrix in `docs/consistency-matrix.md`, that is a security issue regardless of named CVE class.

## Hall of Fame

Researchers who report confirmed vulnerabilities are credited here unless they prefer anonymity.

_None yet._
