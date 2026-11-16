# FileShape — proposed HTTP ZIP extraction and multi-file artifact contract

> **DESIGN ONLY / NOT IMPLEMENTED.** Issue [#132](https://github.com/Dimash313/FileShape/issues/132).
> No route in this document is shipped. The existing HTTP API exposes ZIP
> inspection and, in the unmerged architecture stack, ZIP creation; ZIP
> extraction remains Telegram-only. Do not advertise this proposal in
> `GET /api/v1/capabilities` or activate purchase/navigation UI.
> Changes require cross-track agreement, a separate implementation Issue,
> executed exact-head CI and review. GitHub Actions issue #101 is blocking.

## Scope and dependencies

- Application HTTP API owns Telegram-signed authentication, job admission,
  rate limits, owner isolation, quota accounting and output delivery.
- `services.archive_module.ArchiveModulePort.extract` owns ZIP decoding,
  hostile-member validation and ordered safe output. It has no HTTP or
  database dependency.
- The images/archives team owns source/extraction fixes, including draft
  [PR #128](https://github.com/Dimash313/FileShape/pull/128) (no-clobber,
  rollback, source revalidation); **do not duplicate its domain code**.
- Current `api.artifacts.ArtifactStore` is a **single-result** store:
  `complete(job_id, filename, content_type)` and `open_result(job_id)`.
  It cannot safely implement a multi-file result by concatenation, exposed
  paths or one mutable shared filename. Design a separate multi-artifact
  extension with per-file leases and bounded reservations in a follow-up PR.
- Current background jobs, idempotency/quota, temporary workspaces and
  `BoundedFileResponse` / `ResultStream` are reference semantics, not
  proof this new protocol already works. No new queue product, paid
  infrastructure, general account system, website or mobile application.

## Proposed HTTP contract (version 1)

All routes below are **proposed**, with no deployment commitment. Keep them
separate from single-file `POST /api/v1/convert` and its `SUPPORTED`
allowlist. HTTP APIs must not accept client-supplied storage paths.

| Method | Proposed path | Contract |
| --- | --- | --- |
| POST | `/api/v1/zip/extractions` | Multipart `upload`: one ZIP, authenticated; `Idempotency-Key` handled server-side; asynchronously admit once; return 202 and opaque `job_id` on acceptance |
| GET | `/api/v1/zip/extractions/{job_id}` | Owner-only JSON status; on completion return ordered, bounded `files[]` metadata and expiry timestamp |
| GET | `/api/v1/zip/extractions/{job_id}/files/{file_id}` | Owner-only, rate/concurrency-limited bounded file download; no anonymous URLs or signed public bearer links |
| DELETE | `/api/v1/zip/extractions/{job_id}` | Owner-only explicit cancellation/discard. Idempotent for own jobs; cannot delete another tenant's files |

The `job_id` and each `file_id` are independent cryptographically
unpredictable, server-generated opaque identifiers (at least 128 bits).
They are **selectors, not authorization credentials**. Parse with strict
bounded canonical syntax; resolve ownership **before** opening a file,
looking up item metadata, disclosing state, or emitting error details.
Treat a foreign/missing ID identically (404). No direct filesystem path,
user-supplied ZIP name or temporary directory appears in either URL.
Use the same verified Telegram `initData` boundary as current API
processing; standalone FileShape web/native identities remain future work.

### Example response shapes (illustrative schema, not live data)

Accepted: HTTP 202, `Cache-Control: no-store`:
```json
{"schema_version":1,"job_id":"<opaque_job_id>","state":"queued"}
```

Completed status: HTTP 200, `Cache-Control: no-store`:
```json
{"schema_version":1,"job_id":"<opaque_job_id>","state":"completed","expires_at":"<UTC_ISO8601>","files":[{"file_id":"<opaque_file_id>","name":"01_document.txt","size_bytes":1234}]}
```

The angle-bracket strings are **documentation placeholders**, not IDs
clients should transmit. `files[]` contains only names that passed
output-name normalization and integer measured byte counts. The complete
array becomes visible **only after all files are written, validated and
published as one logical result**. Never return a partial success list
after CRC, decoder, disk, subprocess, or quota failure. Terminal failures
use a stable bounded public error code and never expose a local path,
traceback, raw archive member contents or a secret.

States: `queued`, `processing`, `completed`, `failed`,
`cancelled`, `expired` (where an expired/missing artifact may also
produce a non-disclosing 404/410). A 409 indicates an own job that is
not completed; 429 indicates admission or download concurrency limits;
503 indicates unavailable trusted storage or quota enforcement. The
`POST` response must not claim completed extraction before the worker
has validated and published every item.

## Hard limits and trust boundaries

All limits apply **server-side**, independent of frontend controls:

- One ZIP input, total HTTP upload <=20 MiB **actual streamed bytes**.
  The ingress guard handles missing/chunked Content-Length and malformed
  framing. Empty, corrupt, encrypted or malicious ZIPs fail closed.
- Existing archive preflight still limits to <=100 entries, <=10
  extracted non-directory regular members, <=20 MiB per member,
  <=50 MiB aggregate expanded bytes, and rejects suspicious ratios above
  200:1 for members >128 KiB. Do not relax ZIP bomb defenses for parity.
- Validate decoded bytes **while streaming**; zip-slip, absolute/drive
  paths, symlinks, special files, duplicate normalized names, and source
  replacement must not escape the controlled workspace. Preserve original
  order with safe de-duplicated filenames. A failed member/publish step
  rolls back all newly created outputs; no partial downloadable result.
- Per-job storage admission reserves a conservative sum of upload,
  staging and worst-case decompressed/output bytes **before starting**,
  bounded by global RAM/CPU/queue/disk budgets. Do not count only ZIP
  compressed bytes. Actual budgets must include any temporary duplicate
  during atomic staging; return 429/503 when unavailable, not unbounded
  disk use. Release reservations on failures, expiry and final lease close.
- Permit at most 10 result descriptors per completed job, with capped
  metadata bytes and a finite result TTL (proposed <=3600 seconds
  measured from successful publication). No indefinite retention.
  A restarted process may invalidate per-boot artifacts; never promise
  restart-safe downloads without a separately designed durable adapter.
- Constrain extraction workers by existing CPU/memory/time limits; use
  `O_NOFOLLOW`, owned private directories and regular-file/inode checks
  at publication and at **every** download open. No trust in filename
  suffix or claimed MIME.

## Atomic publication, download and cleanup

1. Admit an owner-scoped job and one quota reservation; acquire bounded
   queue/storage capacity before durable acceptance.
2. Stage the input under a server-generated private path. The worker
   validates the same on-disk bytes it actually opens, extracts to a
   private no-clobber stage and checks real output counts, CRC and sizes.
3. Publish **one immutable manifest plus N immutable private item
   handles** atomically. If any handle is absent, unsafe or over budget,
   fail the whole job, delete staged outputs and settle quota as failed.
4. File download checks authenticated owner and job state before
   retrieving an item. Open the exact regular file via a directory fd
   without following links, hold a per-item download lease and byte
   reservation until streaming ends/disconnects/times out (<=120s
   proposed). Concurrent delete/TTL can unlink names but not invalidate
   an open fd; no new lease after expiry/discard.
5. Return `application/octet-stream`, `Content-Disposition: attachment`
   with safe quoted/encoded filenames, `Cache-Control: no-store`,
   `X-Content-Type-Options: nosniff` and exact verified
   `Content-Length`. Never serve extracted HTML/SVG/etc inline.
   Do not enable Range/partial-content downloads without independently
   implementing correct lease, size and abuse semantics.
6. Terminal cleanup removes workspaces and artifact metadata, including
   crash or shutdown recovery. If removal fails, retain a bounded
   reclaimable record and log a sanitized error; do not silently return
   success or release disk reservations prematurely.

## Quota and idempotency

A requested archive extraction is **one operation**, not one operation
per member or download. Reserve exactly once for an accepted job using
a server-controlled owner/job key. Settle success only after the full
atomic manifest publishes; rejected, failed and cancelled jobs release
the reservation, including timeout, restart and quota-ledger errors.
Never grant a client access merely because it supplies a `job_id`.

For one owner, identical request idempotency keys with matching request
identity must return the existing job without a second quota debit.
Reusing a key with different upload identity is a conflict; foreign
owners cannot use another owner's idempotency key to get status. If
artifacts expire or are lost on restart, the old key must not return
a fabricated `completed` download. A fresh operation requires a new
key and a new reservation. Concurrent retries, day rollover and pack
usage must remain transactionally correct.

## Required tests before implementation may ship

- Signed auth required on **every** route; foreign/missing/invalid/expired
  identities, guessed file IDs and cross-user idempotency keys disclose
  nothing. Quota denied, subscription denied and 429/503 paths tested.
- Ordinary ZIP, nested entries, Unicode, duplicate basename and 1/10
  member controls; verify stable order and exact byte roundtrip.
- Malformed/truncated ZIP, corrupt second-member CRC, symlinks, special
  entries, traversal, absolute paths, encryption, >100 entries,
  >10 result files, member >20 MiB, total >50 MiB, compression ratio,
  streamed upload >20 MiB without Content-Length.
- Stage/publish error after several files leaves **zero** visible
  artifacts and restores reservations. Inject symlink/path substitution
  between preflight, open, publish, and download.
- Concurrent downloads, DELETE/TTL while an fd is leased, disconnect,
  120-second timeout, disk exhaustion, crashed worker, process restart,
  failed cleanup/reconciliation and orphan sweeper behavior.
- Duplicate/replayed/conflicting idempotency requests, racing expiry,
  cancelled job, day reset, one-time quota settlement and exact
  error-state contract. No client-provided raw paths.
- End-to-end genuine HTTP and generated neutral ZIP fixtures in worker
  isolation, full Python/Mini App tests and Docker CI on the final
  head **with actual executed steps**. Review with `images-archives`
  before implementation; UI is deferred.

## Integration decision / rollout gate

The contract and new multi-artifact store require an explicit follow-up
implementation Issue, shared API/security review, images/archives signoff
and compatibility review with #107–#109 and #128. Add a route descriptor
to `/api/v1/capabilities` **only in the same PR that implements
and tests that HTTP route**, after reconciling PR #87/#107 duplication.

PRs #87 and #107 both propose HTTP capability discovery; #107 is the
stacked-architecture successor (with batch-route descriptions). Do
not independently merge both copies or overwrite manifests. Integration
owner must decide whether to close #87 as superseded after confirming
code-level parity.

GitHub Actions Issue [#101](https://github.com/Dimash313/FileShape/issues/101)
blocks safe merge. Zero-step job failures are not test passes. No new
payments, accounts, external service, infrastructure spend, media assets,
audio, advertising or prohibited/doubtful features are introduced in
this specification.
