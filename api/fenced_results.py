"""Opt-in lease-fenced candidate approval, NOT a production download endpoint.

A FencedDispatchStore extends the offline durable-dispatch prototype; the
normal API does not instantiate it. The gate coordinates trusted private
candidate verification with a single SQLite ledger transaction. It does NOT
make the private blob store and dispatch database crash-atomic, and does not
turn local files into shared multi-server storage.

Never expose owner_id, lease tokens, candidate refs or the gate to clients.
The future service must authenticate both users and worker identities and
must reconcile missing blobs before considering the migration complete.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac

from api.durable_dispatch import (
    DispatchLeaseConflict, DurableDispatchStore, _now,
)
from api.durable_jobs import serialized
from api.job_envelope import SingleFileJobV1
from api.jobs import JobNotFound, JobStateError
from api.private_blob_store import (
    BlobUnavailable, PrivateBlobStore, _valid_id,
)


@dataclass(frozen=True, slots=True)
class ApprovedCandidate:
    """Metadata receipt, not a download authorization or signed URL."""

    job_id: str
    result_ref: str
    candidate_ref: str
    byte_count: int
    sha256: str


class FencedDispatchStore(DurableDispatchStore):
    """Opt-in dispatch subclass refusing success ACKs without file verification."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS approved_candidates (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
                    candidate_ref TEXT NOT NULL CHECK(length(candidate_ref)=32),
                    byte_count INTEGER NOT NULL CHECK(byte_count>0 AND byte_count<=47185920),
                    sha256 TEXT NOT NULL CHECK(length(sha256)=64),
                    approved_at REAL NOT NULL
                )
            """)
        except BaseException:
            self.close()
            raise

    def settle_lease(self, job_id, owner_id, token, *, success, now=None):
        """Successful ACKs MUST use the verified, fenced candidate gate."""
        if type(success) is not bool:
            raise ValueError("Invalid settlement")
        if success:
            raise JobStateError("Successful jobs require candidate approval")
        return super().settle_lease(
            job_id, owner_id, token, success=False, now=now,
        )


class FencedResultGate:
    """Trusted internal prototype joining fenced metadata and private bytes.

    The gate is deliberately separate from the live API. Future production
    authorization, blob lifecycle, crash reconciliation, streaming and worker
    identity checks are out of scope for this release.
    """

    def __init__(self, dispatch: FencedDispatchStore, blobs: PrivateBlobStore):
        if not isinstance(dispatch, FencedDispatchStore):
            raise TypeError("FencedDispatchStore is required")
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore is required")
        self._dispatch = dispatch
        self._blobs = blobs

    @serialized
    def _not_used(self):
        # The gate deliberately does not inherit SQL primitives.
        raise NotImplementedError

    def approve(
        self, owner_id: int, job_id: str, lease_token: str, candidate_ref: str,
        *, now: float | None = None,
    ) -> ApprovedCandidate:
        """Approve only a current unexpired lease and verified private candidate.

        All changes to the job, quota and result pointer commit together in
        the dispatch DB. No file copying/moving takes place in this transaction.
        """
        dispatch = self._dispatch
        dispatch._validate_owner(owner_id)
        if not _valid_id(job_id) or not _valid_id(candidate_ref):
            raise BlobUnavailable()
        timestamp = _now(now)
        with dispatch._lock:
            with dispatch._transaction():
                dispatch._require_current_lease(
                    job_id, owner_id, lease_token, timestamp,
                )
                row = dispatch._db.execute(
                    """SELECT d.envelope, j.state FROM dispatch_outbox d
                       JOIN jobs j ON j.job_id=d.job_id
                       WHERE d.job_id=? AND j.owner_id=? AND d.state='leased'""",
                    (job_id, owner_id),
                ).fetchone()
                if row is None or row[1] != "processing":
                    raise JobStateError()
                envelope = SingleFileJobV1.from_json(row[0])
                if envelope.job_id != job_id:
                    raise JobStateError()
                # No external caller may assert that a candidate is valid:
                # read through the private owner/job-bound storage adapter.
                blob = self._blobs.read_candidate(
                    owner_id, job_id, candidate_ref, now=timestamp,
                )
                length = len(blob)
                digest = hashlib.sha256(blob).hexdigest()
                dispatch._db.execute(
                    """INSERT INTO approved_candidates
                       (job_id,candidate_ref,byte_count,sha256,approved_at)
                       VALUES(?,?,?,?,?)""",
                    (job_id, candidate_ref, length, digest, timestamp),
                )
                changed = dispatch._db.execute(
                    """UPDATE jobs SET state='completed',updated_at=?
                       WHERE job_id=? AND owner_id=? AND state='processing'""",
                    (timestamp, job_id, owner_id),
                ).rowcount
                if changed != 1:
                    raise JobStateError()
                dispatch._settle_job_operation_in_transaction(
                    job_id, owner_id, success=True, now=timestamp,
                )
                changed = dispatch._db.execute(
                    """UPDATE dispatch_outbox
                       SET state='completed',lease_hash=NULL,
                           lease_until=NULL,updated_at=?
                       WHERE job_id=? AND state='leased'""",
                    (timestamp, job_id),
                ).rowcount
                if changed != 1:
                    raise DispatchLeaseConflict()
                return ApprovedCandidate(
                    job_id=job_id, result_ref=envelope.result_ref,
                    candidate_ref=candidate_ref, byte_count=length,
                    sha256=digest,
                )

    def read_approved(
        self, owner_id: int, job_id: str, result_ref: str,
        *, now: float | None = None,
    ) -> bytes:
        """Authorized-by-trusted-caller read, never a public endpoint.

        A caller must authenticate the owner separately. A completed state
        without an approved pointer fails closed. Blob expiry/corruption also
        fails closed: cross-DB durability and accounting recovery remain gates.
        """
        dispatch = self._dispatch
        dispatch._validate_owner(owner_id)
        if not _valid_id(job_id) or not _valid_id(result_ref):
            raise JobNotFound()
        timestamp = _now(now)
        with dispatch._lock:
            row = dispatch._db.execute(
                """SELECT d.envelope,a.candidate_ref,a.byte_count,a.sha256
                   FROM approved_candidates a
                   JOIN jobs j ON j.job_id=a.job_id
                   JOIN dispatch_outbox d ON d.job_id=j.job_id
                   WHERE j.job_id=? AND j.owner_id=?
                     AND j.state='completed' AND d.state='completed'""",
                (job_id, owner_id),
            ).fetchone()
        if row is None:
            raise JobNotFound()
        envelope = SingleFileJobV1.from_json(row[0])
        if envelope.job_id != job_id or not hmac.compare_digest(
            envelope.result_ref, result_ref,
        ):
            raise JobNotFound()
        content = self._blobs.read_candidate(
            owner_id, job_id, row[1], now=timestamp,
        )
        if len(content) != row[2] or not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(), row[3],
        ):
            raise BlobUnavailable()
        return content
