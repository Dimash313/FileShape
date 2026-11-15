# FileShape 5.0.11 — expired processing input recovery (offline only)

**Status:** opt-in review protocol built on the unmerged FileShape 5.0.9
input handoff. NOT enabled in the API, JobRuntime, bot or any worker.
The PR is stacked on 5.0.9 and cannot be merged to main before its parent
passes its own safety and CI gates.

## Why this is needed

FileShape 5.0.9 verifies private owner/job-bound inputs before every
dispatch lease. If a file vanishes after it was first leased, the following
expired-lease claim demotes its handoff record to `suspect` to prevent
a broken re-lease. The job is still `processing`, the lease is expired,
and its operation reservation remains occupied. The queued-input repair
flow intentionally cannot alter such jobs.

This extension addresses **only** the now-expired processing lease with a
suspect input and a remaining attempt budget.

## Bounded recovery

1. `InputHandoff.recover_processing()` scans at most 100 expired,
   suspect/review **processing** leases. Active leases, completed/cancelled
   jobs and exhausted attempt budgets are excluded.
2. `inspect_expired_processing_input()` verifies actual owner/job-bound
   private bytes and TTL under a dispatch SQLite `BEGIN IMMEDIATE`
   transaction. If the input is now healthy, it restores `ready`, allowing
   a later normal `claim_next(blobs)` to issue a **new fenced token**.
3. A first failure from the claim-time recheck is `suspect`. A second
   failure, separated by at least 30 seconds by default, becomes
   `review`. The scan **never** bills, automatically fails or silently
   refunds the user.
4. A separately authorized human/operator can call
   `resolve_expired_processing_review()`. It re-verifies the bytes under
   the dispatch write transaction. If restored, it restores readiness
   without a refund. If still missing, it atomically sets the job and
   dispatch record to `failed`, invalidates the old lease hash and commits
   a once-only **failed** quota settlement in the same ledger transaction.
5. Cancellation or a stale competing reviewer cannot double refund. A
   processing attempt whose lease is still active cannot use this path.

Exhausted attempts remain handled by existing `expire_exhausted()` and
need a separately reviewed operational policy. Do not bypass the attempt
limit just because an input has reappeared.

## Residual production risks

- The file bytes, blob metadata and dispatch ledger are NOT one
  crash-atomic transaction. Returning readiness is a point-in-time check,
  not a guaranteed durable pin. Missing inputs can reappear or vanish
  between checks. Enforce real worker retrieval authorization and file
  retention before enabling production.
- Missing files may result from a temporary storage outage. A second
  failure is **not** proof of irrecoverable data loss; human/operator
  resolution is mandatory. No untrusted user, bot callback or client
  may call the review or settlement primitives directly.
- This adapter does not track downloaded chunks, multi-file operations,
  paid Stars receipts, credits after natural result expiry or cross-replica
  storage. Live `JobRuntime` remains unchanged.
- The worker may have already made a candidate artifact before its lease
  expired; such stale lease cannot publish through `FencedResultGate`.
  Orphan cleanup and verified output delivery still require explicit
  integration and retention.
- New tests cover expiry, review delay, restoration, old-token fencing,
  cancellation, foreign owner, concurrency and exactly-once refunds.
  These tests are committed, **not proven passing** until CI works.

## Halal and product scope

No new content, images, music, paid APIs, advertising, billing, dependencies,
or external services are added. `AGENTS.md` remains binding.

**Release gate:** successful Python tests, Mini App TypeScript/build, Docker
build on the *exact final head SHA*, parent PR 5.0.9 approved/merged first,
then green post-merge main CI. Do not deploy these experimental adapters
before an independently reviewed integration/reconciliation plan.
