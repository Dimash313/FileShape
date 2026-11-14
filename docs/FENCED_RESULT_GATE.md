# FileShape 5.0.7 — lease-fenced result approval gate

**Scope: offline opt-in prototype only.** The new classes in
api/fenced_results.py are NOT instantiated by api.server, JobRuntime, Telegram
Bot, mini app, workers or a public download route. Existing user conversions
and billing remain unchanged. This phase does not enable multiple API hosts,
account sync, payment checkout or cloud storage.

## Architecture

The two independent private adapters remain:

- FencedDispatchStore: subclass of the offline DurableDispatchStore. It adds
  an approved_candidates ledger in the dispatch SQLite database. Entries hold
  only job ID, opaque candidate reference, SHA-256 digest, byte count and
  approval time. No user file bytes, original names or worker secrets.
- PrivateBlobStore: holds staged input/candidate bytes in a restricted local
  directory; every read verifies owner, job, expiry, inode and SHA-256.
- FencedResultGate: trusted internal composition service. It never accepts
  an arbitrary worker claim that a file is valid: it calls the private blob
  adapter to read and verify the candidate.

## Approval transaction

1. A caller already authenticated as the server's trusted orchestration layer
   requests approval for the authoritative owner ID, job ID, current lease
   token and candidate reference.
2. The gate begins an atomic SQLite BEGIN IMMEDIATE transaction and checks
   that the lease is current, unexpired and bound to that owner and job.
3. The envelope and job state must match the leased operation.
4. It reads the candidate via PrivateBlobStore.read_candidate(owner, job, ref).
   A missing/expired, foreign, altered or unsafe file rejects approval.
5. In the SAME dispatch SQLite transaction, it records the approved pointer,
   marks the job completed, commits the quota reservation exactly once, and
   clears the lease. If any step fails, all these ledger changes roll back.
6. A later trusted read requires matching job owner, completed states,
   expected result_ref from the envelope and an existing approved pointer.
   It re-checks the candidate blob's length, hash, permissions and expiry.

The opt-in FencedDispatchStore refuses legacy success=True settle_lease ACKs:
success must pass the candidate verification gate. Failed worker ACKs retain
the existing quota-release behavior. A stale or cancelled lease cannot approve
a candidate, and two independent SQLite connections cannot both approve the
same lease.

**The result_ref in SingleFileJobV1 is a logical lookup ID**, not a filesystem
path or bearer credential. The random private candidate_ref remains internal
and distinct from the consumer-facing lookup.

## Critical blockers — NOT a production-ready publisher

- **Not crash-atomic across the two stores.** The dispatch SQLite transaction
  cannot guarantee that private blob bytes remain available after approval;
  deletion, expiry, disk failure or process crash may leave a completed,
  charged job with an unavailable file. The prototype deliberately fails
  closed on read, but it does **not** automatically refund an already
  committed charge. A storage/ledger reconciliation and rollback/compensation
  protocol is mandatory before live use.
- **No shared object store.** PrivateBlobStore uses local disk. Another
  server cannot read the result unless storage is made explicitly shared
  through a separately reviewed authorized adapter.
- **No authenticated remote worker.** Worker-supplied owner IDs or lease
  tokens must never be accepted from an unauthenticated public endpoint.
  There are no network routes or worker APIs in this phase.
- **No durable upload-to-job transaction.** Existing staged input metadata
  and the dispatch job ledger are in separate SQLite databases. Their
  admission and cleanup must be coordinated by trusted recovery code.
- **No streaming/large-file result leases.** The prototype reads complete
  candidate contents into memory (bounded to 45 MiB); no download lease
  prevents expiry during a future public response.
- **No live runtime recovery.** JobRuntime's current startup policy fails
  interrupted in-memory conversions. It has NOT switched to resumable work.
- **No hardening against trusted-code bypass.** The prototype's inherited
  internal DB primitives remain callable by other trusted Python code.
  This gate is not a substitute for a production service boundary with
  authenticated permissions and constrained DB roles.

The automated tests cover stale leases/retries, ownership isolation, invalid
candidate files, cancellation, replay, expiry, reopening and concurrent
approval through two SQLite connections. The test that simulates missing
bytes after successful settlement is intentional and records why deployment
remains blocked.

No new external dependency, API provider, billing integration, music,
imagery, advertising or user-visible file feature is introduced. Follow
AGENTS.md and never enable Stars payments as part of this phase.
