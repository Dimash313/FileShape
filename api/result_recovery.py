"""Offline reconciliation of completed jobs against approved private bytes.

This is an opt-in maintenance component for the FencedDispatchStore prototype.
It is NOT wired to the live API and must never accept client-supplied owner,
job or artifact identifiers. Failure status and quota adjustments are durable
in the same dispatch SQLite transaction, but physical blob storage is still
a separate non-transactional system.

A result missing AFTER its explicitly recorded TTL is normal expiry, not a
reason to return quota. A transient read failure before expiry is only a
"suspect" event. Credit is applied after a second failed verification at
least confirm_after_seconds later, still before the promised expiry.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math

from api.durable_dispatch import _now
from api.fenced_results import FencedDispatchStore
from api.jobs import JobStateError
from api.private_blob_store import BlobUnavailable, PrivateBlobStore
from api.usage_ledger import MAX_PACK_BALANCE


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Aggregate maintenance counts only; never emit filenames or user IDs."""

    checked: int
    suspected: int
    recovered: int
    confirmed_lost: int
    credited: int
    pending_credit: int
    expired: int
    manual_review: int


class ResultRecovery:
    """Internal reconciler for the experimental dispatch/blob adapters."""

    def __init__(self, dispatch: FencedDispatchStore, blobs: PrivateBlobStore):
        if not isinstance(dispatch, FencedDispatchStore):
            raise TypeError("FencedDispatchStore is required")
        if not isinstance(blobs, PrivateBlobStore):
            raise TypeError("PrivateBlobStore is required")
        self._dispatch = dispatch
        self._blobs = blobs

    def _credit_lost(self, owner_id: int, job_id: str, timestamp: float) -> bool:
        """Caller holds dispatch BEGIN IMMEDIATE; refund exactly once.

        When a pack balance has reached its cap since completion, leave a
        *durable pending credit*, never drop a unit or exceed the balance cap.
        Subsequent reconciliation retries once pack capacity is available.
        """
        dispatch = self._dispatch
        operation_key = dispatch._job_operation_key(job_id)
        row = dispatch._db.execute(
            """SELECT owner_id,source,status FROM operation_usage
               WHERE operation_key=?""",
            (operation_key,),
        ).fetchone()
        if row is None or row[0] != owner_id or row[2] != "committed":
            raise JobStateError("Inconsistent usage record for lost result")
        if row[1] == "pack":
            changed = dispatch._db.execute(
                """UPDATE operation_pack_balances SET balance=balance+1
                   WHERE owner_id=? AND balance<?""",
                (owner_id, MAX_PACK_BALANCE),
            ).rowcount
            if changed != 1:
                return False
        elif row[1] != "daily":
            raise JobStateError("Invalid operation funding source")
        changed = dispatch._db.execute(
            """UPDATE operation_usage SET status='released',settled_at=?
               WHERE operation_key=? AND owner_id=? AND status='committed'""",
            (timestamp, operation_key, owner_id),
        ).rowcount
        if changed != 1:
            raise JobStateError("Concurrent usage compensation conflict")
        changed = dispatch._db.execute(
            """UPDATE result_delivery_state SET compensation='credited',
                   last_checked_at=?
               WHERE job_id=? AND status='lost' AND compensation='pending'""",
            (timestamp, job_id),
        ).rowcount
        if changed != 1:
            raise JobStateError("Duplicate compensation state change")
        return True

    def reconcile(
        self, *, now: float | None = None, limit: int = 100,
        confirm_after_seconds: int = 30,
    ) -> RecoveryReport:
        """Bounded maintenance pass over completed result availability.

        Uses BEGIN IMMEDIATE to serialize credit with other quota writers
        across SQLite connections. Candidate reads are private, bounded and
        verified through the storage adapter. Never deletes user artifacts.
        """
        timestamp = _now(now)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid recovery batch")
        if type(confirm_after_seconds) is not int or not 1 <= confirm_after_seconds <= 3600:
            raise ValueError("Invalid confirmation interval")
        dispatch = self._dispatch
        checked = suspected = recovered = lost = credited = pending = expired = review = 0
        with dispatch._lock:
            with dispatch._transaction():
                rows = dispatch._db.execute(
                    """SELECT j.job_id,j.owner_id,a.candidate_ref,a.byte_count,
                              a.sha256,l.available_until,l.status,
                              l.compensation,l.first_missing_at
                       FROM result_delivery_state l
                       JOIN approved_candidates a ON a.job_id=l.job_id
                       JOIN jobs j ON j.job_id=l.job_id
                       JOIN dispatch_outbox d ON d.job_id=l.job_id
                       WHERE j.state='completed' AND d.state='completed'
                         AND (
                           l.status IN ('available','suspect')
                           OR (l.status='lost' AND l.compensation='pending')
                         )
                       ORDER BY COALESCE(l.last_checked_at,0),a.approved_at,j.job_id
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
                for job_id, owner_id, candidate, expected_bytes, expected_hash, \
                        available_until, status, compensation, first_missing in rows:
                    checked += 1
                    if status == "lost":
                        if self._credit_lost(owner_id, job_id, timestamp):
                            credited += 1
                        else:
                            pending += 1
                        continue
                    if timestamp >= available_until:
                        new_state = "review" if status == "suspect" else "expired"
                        dispatch._db.execute(
                            """UPDATE result_delivery_state
                               SET status=?,last_checked_at=? WHERE job_id=?""",
                            (new_state, timestamp, job_id),
                        )
                        if new_state == "review":
                            review += 1
                        else:
                            expired += 1
                        continue
                    try:
                        content = self._blobs.read_candidate(
                            owner_id, job_id, candidate, now=timestamp,
                        )
                        if len(content) != expected_bytes or not hmac.compare_digest(
                            hashlib.sha256(content).hexdigest(), expected_hash,
                        ):
                            raise BlobUnavailable()
                    except BlobUnavailable:
                        if status == "available":
                            dispatch._db.execute(
                                """UPDATE result_delivery_state
                                   SET status='suspect',first_missing_at=?,
                                       last_checked_at=? WHERE job_id=?""",
                                (timestamp, timestamp, job_id),
                            )
                            suspected += 1
                        elif first_missing is None:
                            raise JobStateError("Missing initial failure time")
                        elif timestamp - first_missing < confirm_after_seconds:
                            dispatch._db.execute(
                                """UPDATE result_delivery_state
                                   SET last_checked_at=? WHERE job_id=?""",
                                (timestamp, job_id),
                            )
                        else:
                            dispatch._db.execute(
                                """UPDATE result_delivery_state
                                   SET status='lost',compensation='pending',
                                       confirmed_at=?,last_checked_at=?
                                   WHERE job_id=? AND status='suspect'""",
                                (timestamp, timestamp, job_id),
                            )
                            lost += 1
                            if self._credit_lost(owner_id, job_id, timestamp):
                                credited += 1
                            else:
                                pending += 1
                    else:
                        dispatch._db.execute(
                            """UPDATE result_delivery_state
                               SET status='available',first_missing_at=NULL,
                                   last_checked_at=? WHERE job_id=?""",
                            (timestamp, job_id),
                        )
                        if status == "suspect":
                            recovered += 1
        return RecoveryReport(
            checked=checked, suspected=suspected, recovered=recovered,
            confirmed_lost=lost, credited=credited, pending_credit=pending,
            expired=expired, manual_review=review,
        )
