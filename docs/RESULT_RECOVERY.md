# FileShape 5.0.8 — offline result availability reconciliation

**Status: isolated prototype, NOT deployed or connected to production.**

The opt-in FileShape 5.0.7 gate can mark a job completed while its result
is stored in a separate local private blob store. If the file disappears
later, the metadata and quota ledger remain committed. This phase adds
a bounded, repeatable internal reconciliation mechanism without changing
existing Telegram/API behavior or enabling Stars checkout.

## Availability window and evidence

- At successful fenced result approval, the existing private blob adapter
  supplies the candidate's owner/job-scoped absolute expiry timestamp.
- This deadline is recorded **in the same dispatch SQLite transaction** as
  the approval pointer, completed state and quota commitment. No path, file
  body or API credential is stored.
- The internal approved-result reader rejects missing/expired files and
  a lifecycle state other than available/suspect. Legacy approvals without
  recorded deadlines fail closed and need separate operator migration.
- **Normal expiry is not a compensable outage.** A result missing at or
  after its explicitly recorded TTL changes state to expired, with no
  automatic quota refund.

## Early loss confirmation

The offline ResultRecovery.reconcile method scans at most 100 completed
records at a time, sorted by last checked time, and uses the private
owner/job-scoped file read and SHA-256 verification. It holds dispatch
BEGIN IMMEDIATE for all state and quota changes across SQLite connections.

1. One failed read **before** the promised expiry marks a result suspect.
   It does not alter the accounting. A recovered candidate clears suspicion.
2. A second failed read at least 30 seconds later (configurable to 1–3600
   seconds in tests), still **before** expiry, confirms loss.
3. Confirmed loss makes the result unavailable and atomically changes the
   corresponding committed usage record to released, restoring a Free/Pro
   daily allowance (for its original accounting day) or one operation-pack
   unit. Repeated passes/reopens cannot credit the same operation twice.
4. Pack credits respect the 10,000-unit maximum and reserve headroom for
   *other active pack-funded jobs* that may still fail. If a credit cannot
   fit, the result remains permanently unavailable with a durable
   compensation=pending record; later passes retry after balance headroom
   becomes available. Pending credits must be surfaced to operators.
5. A result that was suspect but is no longer within its promised TTL
   becomes review, **not** an automatic refund. Such ambiguity requires
   investigation rather than using natural expiry as proof of lost bytes.

The job's processing state remains completed; result availability is
tracked separately. This preserves existing historical transitions rather
than pretending a previously completed conversion never happened.

## Important limitations and next release gates

- **No multi-database atomicity:** file bytes and dispatch bookkeeping are
  still in different SQLite databases. This mechanism handles observable
  early losses but cannot guarantee crash-atomic writes or persistent
  availability. A real distributed object store and verified commit protocol
  are still required.
- **Not a durable delivery guarantee:** the prototype has no download lease
  or proof of user delivery. An output can expire naturally before the user
  downloads it. Future user-facing retention terms and download leases must
  be agreed upon before payments are enabled.
- **Transient I/O failures:** a second failure is stronger evidence than
  one but not absolute proof of irreversible corruption. Only authorized
  internal operators/schedulers may initiate reconciliation; production
  deployments need retries, observability, error-classification and
  explicit incident response to avoid compensating during temporary storage
  outages.
- **Pending credits and reviews:** refunds blocked by the pack cap, legacy
  approval rows without deadlines and suspect-then-expired results require
  operator dashboards, documented resolution and safe replay procedures.
- **No global-account rollout:** app/web/iOS/Android identity linking and
  PostgreSQL migration remain later, separately reviewed steps.
- **No live API wiring:** the normal single-worker runtime, legacy
  local-file conversions and existing usage ledger behavior are untouched.

Automated tests cover successful reads, premature deletion, transient
corruption that is repaired, two-stage confirmation, natural expiry,
expiry during suspicion, daily and pack refunds, full pack balance,
cross-connection deduplication, reopen/replay and invalid reconciliation
configuration. This phase makes **no claim** of production readiness,
throughput or multi-server support.

No new dependencies, external APIs, music, imagery, advertisements, payment
providers or new user-visible file transformations are introduced. The
repository-wide AGENTS.md halal requirements remain binding.


## Retention safety

The opt-in FencedDispatchStore now overrides terminal-job pruning so the
normal one-hour metadata retention cannot erase unpaid loss compensation.
Rows remain protected while a credit is pending, a result is suspect,
operator review is required, or the result is still within its recorded
availability window. Deletion of a job after its completed retention
period cascades into its result-availability records *only when no such
condition applies*. This protection is not enabled on the live
DurableJobStore. Operators must monitor unresolved records and enforce
bounded backlog capacity; retaining an unpaid liability is intentional.
