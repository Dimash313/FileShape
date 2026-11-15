"""Offline crash-recoverable *input* handoff for the FileShape 5.0 queue.

This is NOT used by the live API, JobRuntime or Telegram bot. It closes a
specific control-plane gap: committing a job in one SQLite database and
binding its staged input in another cannot form a cross-database transaction.

An accepted job is therefore UNCLAIMABLE until its owner/job-bound input
has been verified and explicitly marked ready in the dispatch database.
A crash before readiness leaves a durable, recoverable queued record.

All methods accept identities from trusted server code only. An opaque file
ID, client key or worker token is never itself proof of authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets

from api.durable_dispatch import (
    DispatchLease, DispatchLeaseConflict, MAX_DELIVERIES, _lease_seconds, _now,
)
from api.durable_jobs import (
    IdempotencyConflict, IdempotencyPending, serialized,
)
from api.fenced_results import FencedDispatchStore
from api.job_envelope import SingleFileJobV1
from api.jobs import JobNotFound, JobStateError
from api.private_blob_store import BlobUnavailable, PrivateBlobStore, _valid_id


@dataclass(frozen=True, slots=True)
class IntakeRecoveryReport:
    examined: int
    made_ready: int
    suspected: int
    needs_review: int
    skipped: int


class IntakeDispatchStore(FencedDispatchStore):
    """Dedicated opt-in dispatch adapter: only verified-ready jobs may lease.

    Historic outbox rows without an intake readiness row fail CLOSED in this
    adapter. A deliberate offline migration is necessary before using it
    with a populated database.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS input_handoff (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
                    state TEXT NOT NULL CHECK(
                        state IN ('ready','suspect','review','failed')
                    ),
                    first_missing_at REAL,
                    input_expires_at REAL,
                    updated_at REAL NOT NULL,
                    CHECK (
                        (state IN ('suspect','review') AND first_missing_at IS NOT NULL
                         AND input_expires_at IS NULL)
                        OR
                        (state='ready' AND first_missing_at IS NULL
                         AND input_expires_at IS NOT NULL)
                        OR
                        (state='failed' AND first_missing_at IS NULL
                         AND input_expires_at IS NULL)
                    )
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_handoff_state
                ON input_handoff(state,updated_at)
            """)
        except BaseException:
            self.close()
            raise

    def _get_queued_input(self, owner_id: int, job_id: str):
        self._validate_owner(owner_id)
        if not _valid_id(job_id):
            raise JobNotFound()
        row = self._db.execute(
            """SELECT d.envelope,h.state,h.first_missing_at,h.input_expires_at
               FROM dispatch_outbox d JOIN jobs j ON j.job_id=d.job_id
               LEFT JOIN input_handoff h ON h.job_id=d.job_id
               WHERE d.job_id=? AND j.owner_id=?
                 AND j.state='queued' AND d.state='queued'""",
            (job_id, owner_id),
        ).fetchone()
        if row is None:
            raise JobNotFound()
        envelope = SingleFileJobV1.from_json(row[0])
        if envelope.job_id != job_id:
            raise JobStateError()
        return envelope, row[1], row[2], row[3]

    @serialized
    def lookup_admission(
        self, owner_id: int, key_hash: str, fingerprint: str,
    ) -> SingleFileJobV1 | None:
        """Owner-scoped replay without restaging or charging another input.

        This is a fast path, NOT a substitute for the underlying atomic
        insert's duplicate-key protection when two submissions race.
        """
        self._validate_owner(owner_id)
        self._validate_admission_hash(key_hash)
        self._validate_admission_hash(fingerprint)
        row = self._db.execute(
            """SELECT a.fingerprint,a.accepted,d.envelope
               FROM admissions a
               JOIN jobs j ON j.job_id=a.job_id
               LEFT JOIN dispatch_outbox d ON d.job_id=a.job_id
               WHERE a.owner_id=? AND a.key_hash=? AND j.owner_id=?""",
            (owner_id, key_hash, owner_id),
        ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise IdempotencyConflict()
        if not row[1] or row[2] is None:
            raise IdempotencyPending()
        return SingleFileJobV1.from_json(row[2])

    @serialized
    def input_status(self, owner_id: int, job_id: str):
        """Trusted owner-scoped lookup of queued unready handoff metadata."""
        return self._get_queued_input(owner_id, job_id)

    @serialized
    def pending_inputs(self, *, now: float | None = None, limit: int = 100):
        timestamp = _now(now)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid handoff scan limit")
        rows = self._db.execute(
            """SELECT j.owner_id,d.envelope
               FROM dispatch_outbox d JOIN jobs j ON j.job_id=d.job_id
               LEFT JOIN input_handoff h ON h.job_id=d.job_id
               WHERE j.state='queued' AND d.state='queued'
                 AND (
                     h.state IS NULL OR h.state IN ('suspect','review')
                     OR (h.state='ready' AND h.input_expires_at<=?)
                 )
               ORDER BY COALESCE(h.updated_at,0),d.created_at,d.job_id LIMIT ?""",
            (timestamp, limit,),
        ).fetchall()
        result = []
        for owner_id, payload in rows:
            result.append((owner_id, SingleFileJobV1.from_json(payload)))
        return result

    @serialized
    def mark_input_ready(
        self, owner_id: int, job_id: str, input_ref: str,
        blobs: PrivateBlobStore, *, now: float | None = None,
    ) -> bool:
        """Check bound bytes AGAIN under the dispatch transaction before ready.

        No arbitrary trusted caller may set ready just by supplying a valid
        string. This still cannot pin local file bytes for the full lease.
        """
        timestamp = _now(now)
        if not _valid_id(input_ref):
            raise BlobUnavailable()
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore required")
        with self._transaction():
            envelope, state, _, _ = self._get_queued_input(owner_id, job_id)
            if envelope.input_ref != input_ref:
                raise BlobUnavailable()
            if state == "failed":
                raise JobStateError()
            blobs.read_input(owner_id, job_id, input_ref, now=timestamp)
            expires = blobs.input_expires_at(
                owner_id, job_id, input_ref, now=timestamp,
            )
            if state == "ready":
                return False
            self._db.execute(
                """INSERT INTO input_handoff
                   (job_id,state,first_missing_at,input_expires_at,updated_at)
                   VALUES(?,'ready',NULL,?,?)
                   ON CONFLICT(job_id) DO UPDATE
                   SET state='ready',first_missing_at=NULL,
                       input_expires_at=excluded.input_expires_at,
                       updated_at=excluded.updated_at""",
                (job_id, expires, timestamp),
            )
            return True

    @serialized
    def mark_input_unavailable(
        self, owner_id: int, job_id: str, input_ref: str, *,
        now: float | None = None, review_after_seconds: int = 30,
    ) -> str:
        """Durable fault evidence, never automatic cancellation/refund.

        Reconciliation cannot prove irreversible loss from a single I/O
        failure. After two checks beyond the review interval, a job is held
        for operator review, not silently failed or charged indefinitely.
        """
        timestamp = _now(now)
        if not _valid_id(input_ref):
            raise BlobUnavailable()
        if type(review_after_seconds) is not int or not 1 <= review_after_seconds <= 3600:
            raise ValueError("Invalid review interval")
        with self._transaction():
            envelope, status, missing_since, input_until = self._get_queued_input(
                owner_id, job_id,
            )
            if envelope.input_ref != input_ref:
                raise BlobUnavailable()
            if status == "ready":
                # Expired ready inputs must not remain claimable forever.
                # A live ready file is not demoted on a racing stale scan.
                if input_until is not None and input_until > timestamp:
                    return "ready"
                self._db.execute(
                    """UPDATE input_handoff
                       SET state='suspect',first_missing_at=?,
                           input_expires_at=NULL,updated_at=?
                       WHERE job_id=? AND state='ready'""",
                    (timestamp, timestamp, job_id),
                )
                return "suspect"
            if status == "failed":
                raise JobStateError()
            if missing_since is None:
                self._db.execute(
                    """INSERT INTO input_handoff
                       (job_id,state,first_missing_at,input_expires_at,updated_at)
                       VALUES(?,'suspect',?,NULL,?)""",
                    (job_id, timestamp, timestamp),
                )
                return "suspect"
            if status == "review" or timestamp - missing_since >= review_after_seconds:
                self._db.execute(
                    """UPDATE input_handoff SET state='review',updated_at=?
                       WHERE job_id=? AND state IN ('suspect','review')""",
                    (timestamp, job_id),
                )
                return "review"
            self._db.execute(
                """UPDATE input_handoff SET updated_at=?
                   WHERE job_id=? AND state='suspect'""",
                (timestamp, job_id),
            )
            return "suspect"

    @serialized
    def claim_next(
        self, blobs: PrivateBlobStore, *,
        now: float | None = None, lease_seconds: int = 60,
    ) -> DispatchLease | None:
        """Verify owner-bound input bytes again before every worker lease.

        The dispatch write transaction serializes the readiness re-check and
        lease issuance. This cannot keep file bytes pinned after the lease,
        but missing/corrupt files will not be handed to a worker at claim.
        A missing queued input is marked suspect for recovery; an expired
        processing lease with missing bytes remains unclaimable pending
        operator recovery, not silently charged or delivered.
        """
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore required for verified claims")
        timestamp = _now(now)
        seconds = _lease_seconds(lease_seconds)
        self.expire_exhausted(now=timestamp)
        with self._transaction():
            # Limit file I/O per claim; never scan a whole large queue while
            # holding the dispatch database's exclusive write lock.
            rows = self._db.execute(
                """SELECT d.job_id,d.envelope,d.state,d.attempts,
                          j.state,j.owner_id,h.input_expires_at
                   FROM dispatch_outbox d
                   JOIN jobs j ON j.job_id=d.job_id
                   JOIN input_handoff h
                     ON h.job_id=d.job_id AND h.state='ready'
                       AND h.input_expires_at>?
                   WHERE d.state='queued'
                      OR (d.state='leased' AND d.lease_until<=?
                          AND d.attempts<?)
                   ORDER BY d.created_at,d.job_id LIMIT 4""",
                (timestamp, timestamp, MAX_DELIVERIES),
            ).fetchall()
            for job_id, payload, state, attempts, job_state, owner_id, expiry in rows:
                if (state == "queued" and job_state != "queued") or (
                    state == "leased" and job_state != "processing"
                ):
                    raise JobStateError()
                envelope = SingleFileJobV1.from_json(payload)
                if envelope.job_id != job_id:
                    raise JobStateError()
                try:
                    blobs.read_input(
                        owner_id, job_id, envelope.input_ref, now=timestamp,
                    )
                    if blobs.input_expires_at(
                        owner_id, job_id, envelope.input_ref, now=timestamp,
                    ) != expiry:
                        raise BlobUnavailable()
                except BlobUnavailable:
                    if state == "queued":
                        self._db.execute(
                            """UPDATE input_handoff
                               SET state='suspect',first_missing_at=?,
                                   input_expires_at=NULL,updated_at=?
                               WHERE job_id=? AND state='ready'""",
                            (timestamp, timestamp, job_id),
                        )
                    # Expired leased jobs need a separate reviewed failure
                    # path. Never claim again while input is unavailable.
                    continue
                if state == "queued":
                    changed = self._db.execute(
                        """UPDATE jobs SET state='processing',updated_at=?
                           WHERE job_id=? AND state='queued'""",
                        (timestamp, job_id),
                    ).rowcount
                    if changed != 1:
                        raise JobStateError()
                token = secrets.token_urlsafe(24)
                lease_until = timestamp + seconds
                changed = self._db.execute(
                    """UPDATE dispatch_outbox SET state='leased',
                       attempts=attempts+1,lease_hash=?,lease_until=?,updated_at=?
                       WHERE job_id=? AND state=?""",
                    (hashlib.sha256(token.encode("ascii")).hexdigest(),
                     lease_until, timestamp, job_id, state),
                ).rowcount
                if changed != 1:
                    raise DispatchLeaseConflict()
                return DispatchLease(envelope, token, attempts + 1, lease_until)
            return None

    @serialized
    def fail_reviewed_input(
        self, owner_id: int, job_id: str, blobs: PrivateBlobStore, *,
        now: float | None = None,
    ) -> bool:
        """Trusted operator resolution: fail/refund only a still-missing input.

        Never callable by a user-facing endpoint. Check again under the
        dispatch transaction, so a concurrent handoff cannot become ready
        between verification and the terminal-state refund. A recovered
        input instead becomes ready; return False.
        """
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore required")
        timestamp = _now(now)
        with self._transaction():
            envelope, status, _, _ = self._get_queued_input(owner_id, job_id)
            if status != "review":
                raise JobStateError("Input is not pending operator review")
            try:
                blobs.bind_input(owner_id, job_id, envelope.input_ref, now=timestamp)
                blobs.read_input(owner_id, job_id, envelope.input_ref, now=timestamp)
            except BlobUnavailable:
                changed = self._db.execute(
                    """UPDATE jobs SET state='failed',updated_at=?
                       WHERE job_id=? AND owner_id=? AND state='queued'""",
                    (timestamp, job_id, owner_id),
                ).rowcount
                if changed != 1:
                    raise JobStateError()
                self._settle_job_operation_in_transaction(
                    job_id, owner_id, success=False, now=timestamp,
                )
                self._db.execute(
                    """UPDATE dispatch_outbox SET state='failed',updated_at=?
                       WHERE job_id=? AND state='queued'""",
                    (timestamp, job_id),
                )
                self._db.execute(
                    """UPDATE input_handoff
                       SET state='failed',first_missing_at=NULL,
                           input_expires_at=NULL,updated_at=?
                       WHERE job_id=? AND state='review'""",
                    (timestamp, job_id),
                )
                return True
            expires = blobs.input_expires_at(
                owner_id, job_id, envelope.input_ref, now=timestamp,
            )
            self._db.execute(
                """UPDATE input_handoff
                   SET state='ready',first_missing_at=NULL,
                       input_expires_at=?,updated_at=?
                   WHERE job_id=? AND state='review'""",
                (expires, timestamp, job_id),
            )
            return False


class InputHandoff:
    """Orchestrate staging, dispatch admission, binding and restart repair.

    Each operation is idempotent at the metadata level; the two SQLite
    databases still do NOT support a single atomic cross-database commit.
    """

    def __init__(self, dispatch: IntakeDispatchStore, blobs: PrivateBlobStore):
        if not isinstance(dispatch, IntakeDispatchStore):
            raise TypeError("IntakeDispatchStore required")
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore required")
        self.dispatch = dispatch
        self.blobs = blobs

    def submit(
        self, owner_id: int, key_hash: str, fingerprint: str, data: bytes,
        *, action: str, suffix: str, pages: str = "",
        ttl: float = 3600, now: float | None = None,
    ) -> tuple[SingleFileJobV1, bool]:
        """For an authenticated caller who already validated uploaded bytes.

        A crash after admission but before binding is repaired by recover().
        Client idempotency keys MUST be hashed and authenticated by API code.
        """
        timestamp = _now(now)
        # A true replay must work even if the private blob store has no
        # capacity for another unused upload. Never replace the original
        # input reference or spend the operation twice.
        existing = self.dispatch.lookup_admission(
            owner_id, key_hash, fingerprint,
        )
        if existing is not None:
            if self.dispatch.get(existing.job_id, owner_id).state == "queued":
                try:
                    self.repair_one(owner_id, existing, now=timestamp)
                except JobNotFound:
                    if self.dispatch.get(existing.job_id, owner_id).state == "queued":
                        raise
            return existing, False
        ref = self.blobs.stage_input(owner_id, data, ttl=ttl, now=timestamp)
        try:
            envelope, created = self.dispatch.admit_staged_single(
                owner_id, key_hash, fingerprint, input_ref=ref,
                result_ref=secrets.token_urlsafe(24),
                action=action, suffix=suffix, pages=pages, now=timestamp,
            )
        except BaseException:
            # Explicit errors: undo the unadmitted staged input. A hard
            # crash is handled later by TTL purge and orphan sweep.
            self.blobs.delete(owner_id, ref)
            raise
        if not created:
            # Never substitute this upload for the accepted job's original
            # reference. That would break idempotency and ownership.
            self.blobs.delete(owner_id, ref)
            # Replayed requests must remain idempotent even after the
            # original job has started or reached a terminal state.
            if self.dispatch.get(envelope.job_id, owner_id).state != "queued":
                return envelope, False
        try:
            self.repair_one(owner_id, envelope, now=timestamp)
        except JobNotFound:
            # A concurrent worker/cancellation may have advanced a queued
            # duplicate after we inspected it. Do not resurrect the job.
            if not created and self.dispatch.get(envelope.job_id, owner_id).state != "queued":
                return envelope, False
            raise
        return envelope, created

    def repair_one(
        self, owner_id: int, envelope: SingleFileJobV1, *,
        now: float | None = None, review_after_seconds: int = 30,
    ) -> str:
        """Rebind the authoritative outbox input after a partial crash."""
        timestamp = _now(now)
        actual, status, _, valid_until = self.dispatch.input_status(
            owner_id, envelope.job_id,
        )
        if actual != envelope:
            raise JobStateError("Mismatch with durable dispatch envelope")
        if status == "ready" and valid_until is not None and valid_until > timestamp:
            return "ready"
        try:
            self.blobs.bind_input(
                owner_id, envelope.job_id, envelope.input_ref, now=timestamp,
            )
            # Binding metadata alone is insufficient: verify the private
            # inode, length, checksum and owner/job before queue readiness.
            self.blobs.read_input(
                owner_id, envelope.job_id, envelope.input_ref, now=timestamp,
            )
            # This second verification is part of the DB readiness commit.
            # A loss between the two reads must remain unready and recorded
            # as suspect rather than escaping the restart sweep.
            self.dispatch.mark_input_ready(
                owner_id, envelope.job_id, envelope.input_ref,
                self.blobs, now=timestamp,
            )
        except BlobUnavailable:
            return self.dispatch.mark_input_unavailable(
                owner_id, envelope.job_id, envelope.input_ref,
                now=timestamp, review_after_seconds=review_after_seconds,
            )
        return "ready"

    def recover(
        self, *, now: float | None = None, limit: int = 100,
        review_after_seconds: int = 30,
    ) -> IntakeRecoveryReport:
        """Explicit bounded restart sweep, never a live startup hook."""
        timestamp = _now(now)
        if type(review_after_seconds) is not int or not 1 <= review_after_seconds <= 3600:
            raise ValueError("Invalid review interval")
        rows = self.dispatch.pending_inputs(now=timestamp, limit=limit)
        ready = suspect = review = skipped = 0
        for owner_id, envelope in rows:
            try:
                state = self.repair_one(
                    owner_id, envelope, now=timestamp,
                    review_after_seconds=review_after_seconds,
                )
            except (JobNotFound, JobStateError):
                # Concurrent cancellation may have made this queued record
                # terminal after the initial scan. Never reopen it.
                skipped += 1
                continue
            if state == "ready":
                ready += 1
            elif state == "suspect":
                suspect += 1
            elif state == "review":
                review += 1
        return IntakeRecoveryReport(
            examined=len(rows), made_ready=ready, suspected=suspect,
            needs_review=review, skipped=skipped,
        )
