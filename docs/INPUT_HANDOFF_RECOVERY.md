# FileShape 5.0.9 — crash-resumable input handoff (offline prototype)

**Status: opt-in contract only. NOT wired to the current FileShape API,
Telegram bot, JobRuntime, Mini App or worker processes.** This does not
make FileShape distributed or guarantee that file bytes are permanently
available across independent hosts.

## The crash gap addressed

FileShape 5.0.5 created a persistent job outbox in the dispatch SQLite
database. FileShape 5.0.6 introduced owner/job-bound local blob staging
in **another** SQLite database. There is no safe cross-database atomic
commit for staging, admission and binding; after a crash the dispatch
job may be queued, but the original input is not yet bound to it.

Previously, the offline dispatch prototype could lease such a queued job
immediately. The new opt-in IntakeDispatchStore fails closed:

1. Input bytes are privately staged after trusted validation.
2. The dispatch database atomically accepts the job, reserves quota
   and records the opaque input reference in its existing outbox.
   **Until readiness is recorded, claim_next cannot lease the job.**
   This is true even if the process crashes before any handoff-state
   row was inserted.
3. InputHandoff binds that exact reference to the accepted owner and job
   in the private blob metadata, then verifies its regular inode,
   ownership, permissions, length and SHA-256 through read_input().
4. Only after successful binding and verification does
   mark_input_ready() create a durable readiness row. Claims are allowed
   only when that row says ready.
5. A duplicate request using the same trusted owner/key/fingerprint
   returns the original job without another charge or changing the
   authoritative reference. A newly staged unused copy is deleted.
   Replays after the job starts or completes return the existing job
   without resurrecting it.

**This is readiness at the moment of verification, not a durable byte
pin or a guarantee the file survives until processing.** Files can still
expire, disappear or be corrupted after readiness is recorded. Input
retention/worker file leases must be designed before live activation.

## Offline recovery and operator resolution

After a simulated restart, InputHandoff.recover() scans at most 100
queued and unready dispatch rows. It can reconstruct the authoritative
owner and opaque input reference from the committed outbox even if
there is *no* handoff-state row. The reconciler retries binding and
integrity verification, making the job claimable if successful.

If the private blob is missing/foreign/expired/corrupt:
- The first failure durably marks suspect; the job remains unclaimable
  and its quota reservation remains intact.
- Further failed verification after a minimum configurable interval
  escalates to review. This is **not automatic proof of irreversible
  loss**: a temporary storage outage should not silently fail a
  user's conversion or discard their upload.
- A verified recovery can turn a suspect/review job ready.
- A **trusted operator-only** fail_reviewed_input() re-verifies under a
  dispatch write transaction. If still missing, it atomically marks
  job and outbox failed and releases the reserved operation **exactly
  once**, invalidating any future queue claim. If the file is now
  intact, it marks ready instead of failing the job.

No automatic review resolution, external service, command, scheduler
or API endpoint is supplied here. Operators need metrics for stuck
queued jobs and a documented response process; stale reviews can
otherwise retain reservations. The existing private blob TTL cleanup
is separate and must not remove unexpired active jobs.

## Security and operational gates

- Only a trusted server layer that has **already authenticated the owner
  and validated uploaded bytes** can submit, bind, inspect or resolve.
  Raw client usernames, Telegram init-data, idempotency keys and worker
  leases must never flow into the database primitives unvalidated.
- All actual job IDs, input refs and result refs remain opaque.
  No OS paths or user filenames are included in the dispatch envelope.
- Two SQLite connections concurrently attempting to claim a job cannot
  claim an unready job; once ready, only one can lease it.
- A cancelled or failed job cannot be made ready or resumed by recovery.
- Historic outbox rows lacking a readiness row are unclaimable when
  using this adapter; migration of existing data must be explicitly
  designed. The old DurableDispatchStore is unchanged and its own
  claim semantics remain available to existing isolated tests.
- This is not a guarantee of exactly-once execution, crash-atomic
  cross-store staging, or reliable worker input downloads. It does
  not support shared-object storage, independent authenticated workers,
  multi-input workflows, quotas for cloud bandwidth or user sync
  across platforms.
- Current JobRuntime deliberately marks interrupted live jobs failed:
  **do not swap it for IntakeDispatchStore**. Startup recovery policy
  and legacy queue draining require separate deployment gates.

Regression tests include crash points before binding and readiness,
cross-owner reference rejection, idempotent replay, restart/reopen,
concurrent claims, restored inputs, suspected loss, operator-only
failure/refund, terminal isolation and invalid payload cleanup.

No payments, music, visuals depicting living beings, advertising,
paid services, third-party dependencies or newly enabled file operations
were added. AGENTS.md remains mandatory.
