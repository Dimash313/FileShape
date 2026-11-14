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
   transactions and Linux file creation/unlink cannot be committed as a
   single transaction. On an unexpected process termination, an orphan
   file can remain after a failed stage, or a deleted metadata record can
   leave a file on disk. A separate offline, exclusive orphan sweeper and
   monitored cleanup process are required before deployment. Do not
   pretend TTL alone guarantees immediate deletion after a crash.
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


## Phase 5.0.6b — crash-orphan reconciliation (opt-in)

The separate PrivateBlobStore now provides reconcile_orphans(), which scans
its dedicated private directory for aged, untracked opaque-identifier files.
It holds SQLite BEGIN IMMEDIATE for the complete scan/delete operation. All
cooperating file stages take the same database write lock *before* creating
an on-disk blob, so an in-progress stage is never mistaken for an orphan
by another SQLite connection. This does not coordinate other noncooperating
writers, so the storage root must remain reserved for this adapter.

Safe deletion requires all of:
- A 32-character opaque reference filename (never path traversal);
- A service-owned regular file with one hardlink and no group/other access;
- No corresponding row in the metadata table, regardless of its TTL;
- A file modification time at least the configured grace period old
  (60 seconds minimum, 5 minutes by default).

Other files, WAL/SHM, symbolic links, hardlinks, recently created files
and *any* metadata-tracked files are deliberately untouched. Deletion is
bounded per call and the directory is fsynced after removals. Reconciliation
is idempotent and must be run explicitly; there is still no production
scheduler, no remote storage and no automatic cleanup guarantee.

**Operator order for future integration:** after starting a validated
private store with exclusive control of the root, periodically run
purge_expired() to remove metadata-tracked expired files, then
reconcile_orphans() to remove old untracked blobs. If storage contents are
untrusted or the metadata DB is damaged, stop and investigate rather than
reconstructing missing metadata or deleting arbitrary files.

This is intentionally separate from dispatch leases: it **cannot publish
a result** and does not solve atomic staging/admission or output fencing.
