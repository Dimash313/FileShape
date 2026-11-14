# FileShape 5.0 — architecture migration contract (proposal)

Status: **design-only, not deployed or benchmarked**. This document defines the migration safety gates; it does not authorize switching production persistence, enabling billing, or promising 100k concurrent users.

## Why the current architecture cannot simply be multiplied

- `api/server.py` documents a single API worker and ephemeral background results.
- `api/job_runtime.py` takes an exclusive `flock` on a local SQLite store; a second API process is explicitly rejected.
- `api/job_manager.py` uses an in-process bounded `asyncio.Queue`; workers and outstanding tasks are not distributed.
- `api/artifacts.py` owns local, per-boot temporary files and leases; another API replica cannot serve them safely.
- `api/durable_jobs.py` holds job metadata, usage reservations, entitlements and campaign state in a service-owned SQLite file.
- Bot-to-API operations use signed, scoped requests. Their identity, idempotency and quota guarantees must survive any migration.
- Telegram Bot API ingress currently enforces 20 MiB. Increasing backend limits alone does not change Telegram transport limits.

These are intentional safeguards for the existing single-instance design, **not defects to bypass by removing locks**.

## Target boundaries (logical modules, not six mandatory microservices)

1. **Ingress**: Telegram bot and Mini App/web/mobile clients; no database ownership or local conversion execution assumptions.
2. **Identity and access**: verify Telegram launch data, signed internal calls, ownership and per-tenant authorization; never trust a client-supplied owner ID.
3. **Operations**: typed, versioned conversion requests, validated resource budgets, server-generated idempotency keys, admission and cancellation.
4. **Accounting**: one authoritative transactional ledger for quota reservation/commit/release, grants and future verified Stars payments.
5. **Dispatch**: durable queue and worker leases, heartbeats, deadlines, bounded retries and dead-letter handling.
6. **Execution**: isolated, resource-limited PDF/image/audio/document/archive workers; no entitlement writes.
7. **Artifacts**: private temporary object storage, short-lived authorized retrieval, encryption/access controls and deletion lifecycle.
8. **Observability**: privacy-safe request/job correlation, queue age, CPU/RAM, failure rates, saturation, security and billing reconciliation alarms.

Start with **modular monolith + separately deployable workers**. A new network service is justified only by measured isolation or scaling needs.

## Non-negotiable invariants

- External API and bot callback behavior remain backward compatible until a separately reviewed versioned change.
- User A cannot read, cancel, bill or enumerate user B's jobs, files or usage, including through guessed IDs and retries.
- Each completed user-requested transformation is charged **at most once**. Failed, rejected or cancelled work does not remain charged; uncertain outcomes must be reconciled durably.
- Durable submission and quota reservation are atomic or reconciled with an auditable recovery protocol. Never acknowledge acceptance before a durable record exists.
- Queue delivery is assumed **at least once**. Workers must be idempotent; execution retries must not create duplicate charges or expose duplicate outputs.
- A worker crash, API restart, network partition or stale lease must not silently lose an accepted job or expose another user's artifacts.
- Cancellation races, expired results and active downloads preserve file cleanup and accounting invariants.
- Do not store raw bot tokens, Telegram init data, original filenames, raw idempotency keys or file bytes in job/accounting records.
- Per-user and global admission limits, CPU/memory/time/disk bounds, backpressure and fair scheduling must be enforced server-side.
- Stars checkout remains disabled until the existing payment PR is independently verified; architecture work must not bypass this gate.
- Keep the existing halal-only requirements in `AGENTS.md`; no new paid providers or infrastructure without owner approval.

## Migration order and release gates

| Phase | Deliverable | Required evidence |
| --- | --- | --- |
| A — baseline | API/ingress inventory, current deployment topology, resource and latency baselines | Reproducible local/CI measurements; label unknowns explicitly |
| B — contracts | Repository interfaces for jobs, accounting, artifacts and dispatch; dependency injection | Contract tests against existing SQLite/in-process implementations; no changed public behavior |
| C — persistence | PostgreSQL-backed transactional ledger and durable job metadata behind interfaces | Migration rehearsal on copied data, backup/restore, rollback, concurrent reserve/settle and crash tests |
| D — dispatch | Durable queue with lease expiry, retry and worker fencing | Duplicate delivery, restart, lost ACK, cancellation and reconciliation tests |
| E — artifacts | Private object-storage adapter and authorized downloads | Cross-replica retrieval, expiry, deletion, leak and quota tests |
| F — scale | Multiple API replicas, independently scaled workers, metrics and rate limiting | Load/soak/failure-injection tests; capacity report with exact hardware and workload |

Each phase ships as **its own branch and PR** with green Python, TypeScript/Mini App and Docker CI. No phase is merged or deployed solely on design review. Use feature flags and staged migration; keep legacy adapters until parity is proven. Database cutover requires an operator-approved backup, dry run and rollback plan.

## Performance SLOs to agree before claiming capacity

Measure **registered users, daily active users, simultaneous uploads, accepted jobs/s, completed jobs/s, p95 API latency, p95 queue wait, p95 conversion time, error rate, RAM/CPU/disk and cost per 1,000 operations** separately. Define representative input sizes and conversion mix. Test sustained load and bursts, plus one worker failure and one API restart. A target of 100,000 accounts is not a claim of 100,000 simultaneous conversions.

## Deferred features

Multi-tenant white-label bot creation is a future product. Do **not** build tenant billing, owner payouts or arbitrary bot creation now. Preserve module boundaries that would allow later evaluation without increasing present scope.

## Phase B2 — conversion catalog boundary

Move the fixed API `SUPPORTED` action allowlists and extension-based
`file_kind` dispatch into `api/conversion_catalog.py`. Existing API exports
remain aliases for backward compatibility. Keep supported operation strings
stable and verify every exposed route keeps its authorization, quota admission,
resource limits and worker-side content validation. Extension classification
is only routing metadata, **not** a trusted file type check or a dynamic plugin
registry. Changes to supported transformations require their own reviewed
operation-level tests.

## Phase B3 — serializable job description (contract only)

[Job envelope v1](JOB_ENVELOPE_V1.md) defines a deterministic, validated,
path-free description of **single-file** work. It references opaque private
artifact IDs and the existing fixed conversion catalog. The envelope is not
wired into the local worker or queue; `api.worker` still runs only with
trusted local paths. Do not advertise distributed worker support until
storage authorization, durable admission, lease fencing and transactional
settlement have been implemented and tested. Multi-file jobs require an
explicit separate contract.


## Phase C0 — opt-in metered outbox prototype (review only)

The separate DurableDispatchStore in api/durable_dispatch.py exercises
single-transaction admission (hashed idempotency + existing quota ledger +
path-free job envelope), SQLite lease acquisition/retry, stale-lease fencing,
owner cancellation, terminal settlement and expired-lease refunds.

Contract tests cover multiple SQLite connections and reopens. See
[DURABLE_DISPATCH.md](DURABLE_DISPATCH.md) for the required production gates.

**No existing route or runtime has been switched.** The current startup
recovery deliberately fails local interrupted jobs and would conflict with
resuming a durable outbox. A future activation PR must redesign restart
recovery, authenticated input staging and fenced artifact publishing, then
prove charge consistency under process crash and duplicate delivery.


## Phase E0 — private local blob staging (5.0.6a; not wired)

The [private staging adapter](PRIVATE_BLOB_STAGING.md) stores actual bytes
in restrictive private files, with owner/job-scoped references, bounded
resources, integrity checks and TTL metadata. It never publishes candidate
outputs. This is a **single-host staging prototype**, not an object-storage
cluster or production asset service. It remains disconnected from the
existing API, bot and workers until cross-component atomic job admission,
stale-lease-fenced result publication and offline orphan cleanup have
independent regression tests.


## Phase E1 — safe orphan reconciliation (5.0.6b; internal only)

The private local blob adapter now supports a bounded, explicit sweep of aged
files not referenced in SQLite. It acquires the SAME BEGIN IMMEDIATE lock as
staging before scanning, so ongoing writes cannot be mistaken for crash
orphans, and ignores all unsupported/unsafe directory entries. This reduces
untracked disk retention after a crash, but is not wired into startup,
scheduling or deployment, and does not resolve durable output publishing,
multi-host sharing or missing referenced blobs. Details and gate tests:
[PRIVATE_BLOB_STAGING.md](PRIVATE_BLOB_STAGING.md).
