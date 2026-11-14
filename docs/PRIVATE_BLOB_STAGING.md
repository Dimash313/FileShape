# FileShape 5.0.6a — private local blob staging (opt-in only)

**Status: isolated adapter; no production integration or remote worker.**
FileShape still uses its existing single-process conversion and artifact
service. The new api/private_blob_store.py is not imported by the API,
Bot, JobRuntime or worker. It is exercised by contract tests only.

## What this phase implements

The PrivateBlobStore persists staged bytes in a dedicated, service-owned
0700 directory. Each file receives a random 32-character opaque name,
with O_EXCL + O_NOFOLLOW creation, 0600 permissions and fsync. Reads verify
the regular-file inode, service ownership, single hardlink, permissions,
length and SHA-256 checksum. The SQLite metadata (also private) contains
only the reference, owner ID, optional job ID, role (input/candidate),
file size, SHA-256 digest, creation time and expiry — **never file bytes,
user filenames, bot tokens, API credentials or raw idempotency keys**.

- Stage bounded inputs (20 MiB maximum, preserving the existing Bot API
  transport boundary) and separately stage bounded candidate results
  (up to 45 MiB for later integrations).
- Bind a staged input to a server-trusted job ID once. Rebinding to a
  different job fails closed.
- Read only owner-and-job-matching, unexpired input or candidate bytes.
  This is a trusted internal service interface, NOT a public download API.
- Stage candidate output without publishing it. No result can be marked
  downloadable by this adapter, even if it has a valid opaque ID.
- Maintain count and byte budgets in a SQLite BEGIN IMMEDIATE transaction;
  a second SQLite connection cannot oversubscribe the logical limits.
- Drop owner-scoped files and purge expired entries with explicit periodic
  maintenance; expired entries cannot be read or bound.

## Remaining blockers before enabling

1. **Job ownership binding is not yet atomic with dispatch admission.**
   The current durable dispatch prototype generates job IDs in its own
   transaction, while this adapter keeps separate SQLite metadata. A future
   integration must ensure only the API-verified owner can bind a staged
   input to the accepted job, and reconcile all partial/crashed operations.
2. **No lease-fenced output publication.** Candidates cannot be downloaded
   via a public endpoint. A future trusted service must validate the
   current dispatch lease, re-verify staged content and commit the output
   publication decision together with quota settlement. Stale/cancelled
   worker attempts must not publish results.
3. **No multi-host storage.** The private blob directory is local to a host.
   It is not visible on other servers, so this does not yet permit horizontal
   scaling. A durable private shared object-storage adapter is needed.
4. **No crash-proof filesystem/database atomicity.** SQLite metadata
   transactions and Linux file creation/unlink cannot be committed as one
   transaction. A bounded **manual** orphan sweeper now detects aged,
   unreferenced private files under a SQLite write lock, including leftovers
   from a crash between a filesystem write and metadata commit, or between
   metadata deletion and unlink. It remains **opt-in, not scheduled or
   monitored**, and does not replace TTL expiration, reconciliation of
   missing or corrupted *referenced* files, or production crash testing.
   File deletion is not guaranteed immediately after any crash.
5. **No independent worker authentication.** Directly passing owner_id,
   job_id or opaque references from an untrusted client is forbidden.
6. **No payments or new file functionality.** Stars remains disabled and
   the project's AGENTS.md halal rules continue to apply.

## Testing gates

Contract tests cover private permissions, symlink/hardlink rejection,
same-size corruption detection, owner isolation, job binding, expiry,
restart persistence, concurrent byte-budget admission and metadata
privacy. Production activation requires separate end-to-end tests for
authorization, rollback and crash recovery, lease-fenced output commit,
blob expiry under concurrent downloads, and multiple-server behavior.

No paid service, new dependency, new API endpoint or content changes
are introduced in this phase.


## Phase 5.0.6b — opt-in orphan reconciliation

Internal method: PrivateBlobStore.sweep_orphans(now=None,
minimum_age_seconds=300, scan_limit=1000, delete_limit=100).

- Takes a SQLite BEGIN IMMEDIATE transaction for the duration of scanning
  and unlinking. All stage operations in this adapter hold that same
  transaction while creating bytes AND inserting their metadata. Therefore
  a second store connection cannot sweep an in-progress stage.
- Only randomly named 32-character blob files absent from staged_blobs
  are eligible. It skips live metadata, fresh files, unexpected names,
  directories, symlinks, hardlinked files and unsafe ownership/permissions.
  It also verifies that the private root has not been replaced since open.
- Age is assessed using filesystem modification time, with an explicit
  300-second default grace period. Sweep is bounded by both scan and delete
  limits; repeat calls are needed for a large backlog.
- Reports aggregate counts only (scanned, removed, preserved_live,
  skipped_young, skipped_unsafe), never filenames or user data.
  Unexpected filesystem failures propagate to the operator for retry.

**No automatic background deletion or public admin endpoint is added.**
Only trusted maintenance code with exclusive access to the private root
should call this operation. Run at startup/periodically only after a
reviewed operator integration and monitoring plan. It is not evidence of
safe multi-server object storage or of a production-ready retention SLA.

Contract tests simulate abandoned private blobs, an in-progress stage
in a second SQLite connection, filesystem root replacement, and malicious
symbolic/hardlink entries without deleting their external targets.
