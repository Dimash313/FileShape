# FileShape — product and engineering roadmap

> Status: living engineering plan, reviewed 2026-11-14. **Not** a public launch, payment enablement, deployment or production-readiness declaration. Every change requires its own branch, PR, green checks on the final head commit and a successful push-triggered main CI run after merging.

## Source of truth and agreed business rules

This document supersedes **proposed** prices, quotas and packaging in [BOT_PRODUCT_ROADMAP.md](BOT_PRODUCT_ROADMAP.md) where they disagree. Keep [ROAD_TO_5.md](ROAD_TO_5.md) as historical engineering gates, not an assertion that outdated pending milestones are still current. Source code and merged PRs determine what is actually implemented.

| Tier / pack | Allowance | Price | Operational caveat |
| --- | --- | --- | --- |
| Free | 10 operations / UTC day | 0 Stars | 20 MiB per file, target maximum one in-flight operation |
| Pro | 100 operations / UTC day | 149 Stars / 30 days | Target 100 MiB per file and three in-flight operations **only if verified** transport and deployment capacity permit; priority queue and batch tools are not shipped |
| Extra 10 | 10 non-expiring operations | 19 Stars | Spend daily allowance first |
| Extra 30 | 30 non-expiring operations | 49 Stars | Spend daily allowance first |

The usage day resets at **00:00 UTC**; successful jobs are charged once, invalid/rejected/failed/cancelled jobs do not consume operations. Reservations must remain protected from concurrent admission and duplicate retries. Packs persist until used. A verified, non-duplicated Telegram Stars transaction must precede any entitlement or pack grant; refunds/reversals require an auditable, consistent policy. Paid functionality and published balance displays must stay disabled until end-to-end accounting is enforced.

## Verified milestones and current gate

| Version | Status | Scope / evidence |
| --- | --- | --- |
| 3.9–4.18 | Previously merged | Durable SQLite job state, security and recovery, conversion APIs, Mini App, access controls and owner advertising infrastructure. Refer to PR history, not proposed features as evidence of deployment |
| 4.19 | Merged | Owner advertising analytics; PR #61 |
| 4.20 | Merged | Telegram home/navigation; PR #62 |
| 4.21 | Merged | Atomic SQLite usage ledger, Free/Pro allowances and packs **without** processing enforcement; PR #63 (PR #64 superseded) |
| 4.22 | Merged | Owner-scoped, read-only `GET /api/v1/usage`, explicit `enforced: false` and `purchases_enabled: false`; PR #65. PR Actions passed; post-merge main Actions must also be confirmed |
| 4.23 | **Next: not implemented** | Attach reservation/settlement to **all** bot/API/Mini App/retry/background submission paths; enforce Free first, preserve user/tenant isolation, no duplicate charges |

### Ordered implementation plan

**4.23 — real usage enforcement (P0).** Inventory every executable conversion admission path, including legacy synchronous endpoints, background jobs, retry and direct API, plus bot callbacks and multi-file workflows. Define one operation per accepted **completed user-requested transformation**, not each input file or status request. Reserve exactly once using a server-owned key (prefer durable job ID), coordinated atomically with job acceptance where possible; compensate safely on all failed admission and terminal outcomes, including cancellation and restart. Handle day rollover, completed replay, lost responses, timeout and multi-worker races. Prevent quota bypass through alternate ingress. Cap concurrent operations server-side by verified tier rather than front-end assertions. Retain 20 MiB Bot API constraints. Add DB/HTTP/bot/restart/concurrency tests. Flip `enforced` only when every path is covered and tests prove it.

**4.24 — Telegram Stars (P0).** Only after 4.23: implement documented Stars digital-service invoice/payment flow with server-verified successful payment, durable unique charge IDs, pending/verified/refunded states, pre-checkout validation, idempotent grants for Pro/10/30 packs, grant reversal or debt policy for refunds, reconciliation and audit tests. No payment acceptance based on untrusted callback data. Test using supported Telegram test environment; keep purchase UI disabled until verified. No additional payment processor.

**4.25 — profile and plans (P1).** Show *real* authenticated remaining daily/pack operations, UTC reset, active Pro expiration and actual verified purchase records in bot and Mini App. Server-side authorization and cache-control on balances; never invent an amount/status. Clear errors and disabled purchase options when billing is unavailable.

**4.26 — premium navigation and file cards (P1).** Clean black/white/graphite design, responsive mobile widths, keyboard/accessibility, concise bot messages, precise file and operation states, honest progress/status, navigable menus and usable errors. Preserve all existing conversion tools.

**4.27+ — utility expansion and hardening (P2).** Prioritize measured demand for new file tools; expand batches and input sizes only after resource/load testing. Complete durable inbound channel-event handling, owner advertising lifecycle, observability, fraud/abuse controls, retention and security audits. Treat client acquisition and monetization as separate business readiness gates, not reasons to bypass safety.

## Technical risks and controls

1. **Split bot/API ingestion:** different paths may bypass quotas; build a complete ingress matrix and end-to-end tests before enabling counters/payments.
2. **Reservation/settlement inconsistency:** crashes between accepted jobs and reservation, lost settlement, retries, cancellation and UTC rollover can overcharge/undercharge. Use transactional patterns, replay-safe state machine and reconciliation; never silently discard unsettled reservations.
3. **SQLite safety and contention:** keep `BEGIN IMMEDIATE`, bounded waits, private service-owned directory, regular non-symlink database and WAL sidecars, locked/CAS state transitions, consistent close/rollback and migration testing.
4. **User privacy and isolation:** verify signed Telegram identity at boundary; server-side IDs only; foreign-user IDs and replay cannot access files, job status or ledger data. Never store uploaded bytes in billing records.
5. **Telegram transport and server capacity:** standard Bot API file downloads are limited; do not promise 100 MiB or higher per-tier parallelism without measured deployment and supported transfer route. Keep CPU/RAM/disk/queue/time/bomb safeguards on both plans.
6. **Payments/refunds:** duplicate update delivery, reversed payments, spoofed callback values, partial grants and audit divergence. Stable transaction keys and operational reconciliation are mandatory.
7. **Deployment/runtime:** bounded temporary uploads/results, subprocess timeouts, bounded queues, recovery after crashes, secret management, Docker resource limits, migrations/backup/rollback and real mobile Telegram testing remain launch blockers.

## Definition of done for each version

- Read current `main`, tests, README, release history and recent Actions before editing.
- Separate branch, scoped PR, migrations and explicit rollback guidance where relevant.
- Regression coverage: successes, failure rollback, stale state, concurrency/replay, tenant isolation, rate/input limits and process restart.
- Python compile + full unittest suite; Mini App Node tests, TypeScript/Vite build; Docker build (all jobs green for **final** PR head).
- Merge only after successful required checks; confirm **push-triggered** `main` workflow for merged commit. Update this roadmap with actual PR links, verified outcomes and outstanding limitations.
- Never claim local/prod testing, throughput, Stars verification or payment revenue without evidence.

## Commercial launch checklist (all required)

- [ ] Quotas correctly enforce **every** bot and HTTP/Mini App ingress path.
- [ ] Release payment verification, idempotency, refund/reconciliation, operational audit with real test payments.
- [ ] Verify tier file size and concurrency claims under expected workload; preserve safe fallbacks.
- [ ] Perform auth/IDOR, parser/ZIP/PDF, resource exhaustion, SQLite/WAL, queue and data-retention security reviews.
- [ ] Verify backup, restore, migration rollback, storage deletion and monitoring on production-like Docker host.
- [ ] Run load tests, end-to-end real Telegram bot/Android Mini App tests, and error-flow regression matrix.
- [ ] Validate product wording, transparent pricing/renewal/refund handling and user privacy disclosures.
- [ ] Launch only with explicit production authorization and an incident/rollback procedure.
