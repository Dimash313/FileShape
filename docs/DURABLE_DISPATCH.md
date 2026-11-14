# FileShape 5.0 — opt-in durable dispatch outbox (prototype)

**Not deployed or connected to FileShape processing.** The production API
continues to use the original single-instance SQLite metadata store,
in-memory bounded queue, and private local working directories.

The new api/durable_dispatch.py defines a separate DurableDispatchStore
subclass of the current SQLite store. It is instantiated only by contract
tests. Existing JobRuntime, bot callbacks and conversion endpoints are
unchanged. It does **not** make FileShape distributed.

## What is now possible at the persistence layer

- A trusted, already-staged single-file job can be admitted with a
  validated SingleFileJobV1 envelope in one BEGIN IMMEDIATE transaction.
  The same transaction inserts the job, reserves quota, records a hashed
  idempotency key plus fingerprint, and writes the outbox row. Failure rolls
  everything back.
- Duplicate admission with the same owner/key/fingerprint returns the
  original envelope without another quota reservation. A changed fingerprint
  fails closed. Hashes are generated and owned by trusted API code, never
  accepted directly from an end user.
- Atomic claim_next leases one pending/expired job. Each attempt increments
  a bounded attempt counter and rotates an opaque token. Only its SHA-256
  digest is kept in SQLite. A stale worker token cannot settle a job.
- Claims can be extended while unexpired. Owner-scoped cancellation invalidates
  the lease and refunds quota. Terminal acknowledgement updates job state,
  ledger and outbox in a single transaction.
- Three expired claims without settlement mark the job failed and release its
  reservation during explicit/claim-triggered reconciliation.
- Tests exercise ownership isolation, concurrent claims through two SQLite
  connections, restart/reopen of this test-only store, replay, stale ACK,
  refund and invalid-envelope rollback.

## Crucial limits and production blockers

1. **No real artifact service.** The caller's assumed "already staged and
   verified" prerequisite has not been connected to any private shared
   storage. Opaque IDs are not access permissions. An authenticated service
   must bind references to owner and job before a worker can access bytes.
2. **No execution wiring.** api.worker still accepts trusted local paths.
   The envelope must never be supplied directly to it or a remote shell.
3. **Startup semantics differ.** The current JobRuntime invokes
   mark_interrupted_failed on queued/processing jobs; that is correct for
   existing ephemeral local jobs but incompatible with resuming durable
   queue leases. Do not inject DurableDispatchStore into the live runtime
   until restart ownership and recovery have dedicated tests.
4. **No durable output commit / fencing.** A late worker may still be
   executing after its lease expires. Future artifact publication must be
   fenced by the server-owned current lease generation and must atomically
   coordinate successful quota settlement. A worker ACK alone is insufficient.
5. **No distributed coordination.** SQLite still permits only the current
   single-instance API deployment. PostgreSQL and independent workers
   require reviewed, migration-tested implementations.
6. **No multi-input workflows.** Photo batches, PDF merges and archive
   assembly need explicit job-envelope contracts and resource controls.
7. **No activation of Stars checkout.** Payment enablement remains blocked
   on separately verified real Telegram test purchases and refunds.

The next migration gates are private artifact staging/authorization,
transactional staging cleanup, token-bound output publishing, compatible
restart recovery, and then an authenticated worker execution protocol. Run
duplicate-delivery, owner isolation, cancellation races, resource exhaustion,
load/soak and fault-injection tests before switching any live routes.

No paid third-party service, music, imagery, advertisement or product-policy
change is introduced. All AGENTS.md constraints remain mandatory.
