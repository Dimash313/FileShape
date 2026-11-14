"""Opt-in result-gate regression tests (not live API or distributed storage)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
import time
import unittest

from api.durable_dispatch import DispatchLeaseConflict
from api.fenced_results import FencedDispatchStore, FencedResultGate
from api.jobs import JobNotFound, JobStateError
from api.private_blob_store import BlobUnavailable, PrivateBlobStore


OWNER = 101
OTHER = 202


class FencedResultGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dispatch_path = Path(self.tmp.name) / "jobs.sqlite3"
        self.blob_path = Path(self.tmp.name) / "blobs"
        self.now = time.time()

    def stores(self):
        return (
            FencedDispatchStore(self.dispatch_path),
            PrivateBlobStore(self.blob_path),
        )

    def admit(self, dispatch, blobs, *, owner=OWNER, key="a" * 64):
        staged = blobs.stage_input(owner, b"%PDF-1.4\nstaged test", now=self.now)
        envelope, created = dispatch.admit_staged_single(
            owner, key, "b" * 64, input_ref=staged,
            result_ref=secrets.token_urlsafe(24),
            action="pdf:extract", suffix=".pdf", pages="1",
            now=self.now,
        )
        self.assertTrue(created)
        self.assertTrue(blobs.bind_input(
            owner, envelope.job_id, staged, now=self.now,
        ))
        return envelope

    def test_approved_result_requires_current_lease_and_is_owner_scoped(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1, lease_seconds=30)
                candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"verified result",
                    now=self.now + 2,
                )
                with self.assertRaises(JobNotFound):
                    gate.read_approved(OWNER, envelope.job_id, envelope.result_ref,
                                       now=self.now + 3)
                with self.assertRaises(JobNotFound):
                    gate.approve(OTHER, envelope.job_id, lease.token, candidate,
                                 now=self.now + 3)
                with self.assertRaises(BlobUnavailable):
                    gate.approve(OWNER, envelope.job_id, lease.token, "Z" * 32,
                                 now=self.now + 3)
                self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "processing")
                approved = gate.approve(OWNER, envelope.job_id, lease.token, candidate,
                                        now=self.now + 3)
                self.assertEqual(approved.job_id, envelope.job_id)
                self.assertEqual(approved.result_ref, envelope.result_ref)
                self.assertEqual(approved.candidate_ref, candidate)
                self.assertEqual(approved.byte_count, len(b"verified result"))
                self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "completed")
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 3,
                )["daily_used"], 1)
                self.assertEqual(
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 4,
                    ),
                    b"verified result",
                )
                with self.assertRaises(JobNotFound):
                    gate.read_approved(OTHER, envelope.job_id, envelope.result_ref,
                                       now=self.now + 4)
                with self.assertRaises(JobNotFound):
                    gate.read_approved(OWNER, envelope.job_id, "X" * 32,
                                       now=self.now + 4)
                with self.assertRaises(DispatchLeaseConflict):
                    gate.approve(OWNER, envelope.job_id, lease.token, candidate,
                                 now=self.now + 4)
                self.assertEqual(dispatch._db.execute(
                    "SELECT COUNT(*) FROM approved_candidates",
                ).fetchone()[0], 1)

    def test_old_attempt_cannot_approve_after_lease_reissued(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                stale = dispatch.claim_next(now=self.now + 1, lease_seconds=2)
                older_candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"stale content", now=self.now + 2,
                )
                fresh = dispatch.claim_next(now=self.now + 4, lease_seconds=15)
                fresh_candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"fresh content", now=self.now + 5,
                )
                with self.assertRaises(DispatchLeaseConflict):
                    gate.approve(OWNER, envelope.job_id, stale.token, older_candidate,
                                 now=self.now + 6)
                approved = gate.approve(
                    OWNER, envelope.job_id, fresh.token, fresh_candidate,
                    now=self.now + 6,
                )
                self.assertEqual(approved.candidate_ref, fresh_candidate)
                self.assertEqual(
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 7,
                    ),
                    b"fresh content",
                )

    def test_cancellation_blocks_publication_and_releases_quota(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"never published", now=self.now + 2,
                )
                self.assertTrue(dispatch.cancel_dispatch(
                    envelope.job_id, OWNER, now=self.now + 3,
                ))
                with self.assertRaises(DispatchLeaseConflict):
                    gate.approve(OWNER, envelope.job_id, lease.token, candidate,
                                 now=self.now + 4)
                with self.assertRaises(JobNotFound):
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref, now=self.now + 4,
                    )
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 4,
                )["daily_used"], 0)

    def test_result_approval_rolls_back_when_candidate_is_corrupted(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"healthy", now=self.now + 2,
                )
                (self.blob_path / candidate).write_bytes(b"corrupt")
                with self.assertRaises(BlobUnavailable):
                    gate.approve(
                        OWNER, envelope.job_id, lease.token, candidate,
                        now=self.now + 3,
                    )
                self.assertEqual(dispatch.get(
                    envelope.job_id, OWNER,
                ).state, "processing")
                self.assertEqual(dispatch._db.execute(
                    "SELECT COUNT(*) FROM approved_candidates",
                ).fetchone()[0], 0)
                fresh = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"healthy", now=self.now + 4,
                )
                gate.approve(OWNER, envelope.job_id, lease.token, fresh,
                             now=self.now + 5)
                self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "completed")

    def test_legacy_success_ack_cannot_bypass_approval(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                with self.assertRaises(JobStateError):
                    dispatch.settle_lease(
                        envelope.job_id, OWNER, lease.token, success=True,
                        now=self.now + 2,
                    )
                with self.assertRaises(JobNotFound):
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 2,
                    )
                self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "processing")

    def test_failed_attempt_never_creates_approved_pointer(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                self.assertTrue(dispatch.settle_lease(
                    envelope.job_id, OWNER, lease.token, success=False,
                    now=self.now + 2,
                ))
                with self.assertRaises(JobNotFound):
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 3,
                    )
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 3,
                )["daily_used"], 0)

    def test_reopen_keeps_approved_reference_private(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"private", now=self.now + 2,
                )
                gate.approve(OWNER, envelope.job_id, lease.token, candidate,
                             now=self.now + 3)
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                self.assertEqual(
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 4,
                    ),
                    b"private",
                )
                self.assertEqual(dispatch._db.execute(
                    "SELECT COUNT(*) FROM approved_candidates",
                ).fetchone()[0], 1)
                self.assertNotIn(
                    b"private", self.dispatch_path.read_bytes(),
                )

    def test_expired_or_deleted_blob_fails_closed_after_approval(self):
        with FencedDispatchStore(self.dispatch_path) as dispatch:
            with PrivateBlobStore(self.blob_path) as blobs:
                gate = FencedResultGate(dispatch, blobs)
                envelope = self.admit(dispatch, blobs)
                lease = dispatch.claim_next(now=self.now + 1)
                candidate = blobs.stage_candidate(
                    OWNER, envelope.job_id, b"finite ttl", now=self.now + 2,
                    ttl=5,
                )
                gate.approve(OWNER, envelope.job_id, lease.token, candidate,
                             now=self.now + 3)
                with self.assertRaises(BlobUnavailable):
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 8,
                    )
                # A missing result must be reconciled before this adapter
                # can ever be used for production billing.
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 8,
                )["daily_used"], 1)

    def test_separate_connections_cannot_both_approve_same_job(self):
        with FencedDispatchStore(self.dispatch_path) as first:
            with FencedDispatchStore(self.dispatch_path) as second:
                with PrivateBlobStore(self.blob_path) as blobs:
                    envelope = self.admit(first, blobs)
                    lease = first.claim_next(now=self.now + 1)
                    candidate = blobs.stage_candidate(
                        OWNER, envelope.job_id, b"one copy", now=self.now + 2,
                    )
                    a = FencedResultGate(first, blobs)
                    b = FencedResultGate(second, blobs)

                    def run(gate):
                        try:
                            return gate.approve(
                                OWNER, envelope.job_id, lease.token, candidate,
                                now=self.now + 3,
                            )
                        except DispatchLeaseConflict:
                            return None

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(run, (a, b)))
                    self.assertEqual(sum(item is not None for item in results), 1)
                    self.assertEqual(first._db.execute(
                        "SELECT COUNT(*) FROM approved_candidates",
                    ).fetchone()[0], 1)
                    self.assertEqual(first.usage_snapshot(
                        OWNER, now=self.now + 3,
                    )["daily_used"], 1)
