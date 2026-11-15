"""Offline recovery of missing input after an expired worker lease.

These tests exercise opt-in storage adapters only. No live API, Telegram bot,
paid checkout or remote worker invokes these trusted recovery primitives.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import time
import unittest

from api.durable_dispatch import DispatchLeaseConflict
from api.input_handoff import InputHandoff, IntakeDispatchStore
from api.jobs import JobNotFound, JobStateError
from api.private_blob_store import PrivateBlobStore


OWNER = 1301
FOREIGN = 1302
PDF = b"%PDF-1.4\nFileShape input recovery test bytes"


class ProcessingInputRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "dispatch.sqlite"
        self.root = Path(temp.name) / "blobs"
        self.now = time.time()

    def started_then_missing(self, dispatch, blobs):
        envelope, created = InputHandoff(dispatch, blobs).submit(
            OWNER, "a" * 64, "b" * 64, PDF,
            action="pdf:extract", suffix=".pdf", pages="1", now=self.now,
        )
        self.assertTrue(created)
        lease = dispatch.claim_next(blobs, now=self.now + 1, lease_seconds=2)
        self.assertEqual(lease.envelope, envelope)
        # Model disk loss while keeping the original bound SQLite metadata.
        (self.root / envelope.input_ref).unlink()
        # A new worker must never be handed bytes that have disappeared.
        self.assertIsNone(dispatch.claim_next(blobs, now=self.now + 4))
        state = dispatch._db.execute(
            "SELECT state FROM input_handoff WHERE job_id=?",
            (envelope.job_id,),
        ).fetchone()[0]
        self.assertEqual(state, "suspect")
        self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "processing")
        return envelope, lease

    def restore(self, envelope):
        path = self.root / envelope.input_ref
        path.write_bytes(PDF)
        path.chmod(0o600)

    def test_review_then_operator_failure_refunds_once_and_fences_old_lease(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            envelope, old = self.started_then_missing(dispatch, blobs)
            recovery = InputHandoff(dispatch, blobs)
            initial = recovery.recover_processing(now=self.now + 10)
            self.assertEqual((initial.examined, initial.suspected), (1, 1))
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 10)["daily_used"], 1)
            with self.assertRaises(JobStateError):
                dispatch.resolve_expired_processing_review(
                    OWNER, envelope.job_id, blobs, now=self.now + 11,
                )
            later = recovery.recover_processing(now=self.now + 35)
            self.assertEqual((later.examined, later.needs_review), (1, 1))
            self.assertTrue(dispatch.resolve_expired_processing_review(
                OWNER, envelope.job_id, blobs, now=self.now + 36,
            ))
            self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "failed")
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 36)["daily_used"], 0)
            self.assertIsNone(dispatch.claim_next(blobs, now=self.now + 37))
            with self.assertRaises(DispatchLeaseConflict):
                dispatch.renew_lease(
                    envelope.job_id, OWNER, old.token, now=self.now + 37,
                )
            with self.assertRaises(JobNotFound):
                dispatch.resolve_expired_processing_review(
                    OWNER, envelope.job_id, blobs, now=self.now + 38,
                )

    def test_temporary_missing_file_can_be_restored_and_released_for_retry(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            envelope, old = self.started_then_missing(dispatch, blobs)
            self.restore(envelope)
            report = InputHandoff(dispatch, blobs).recover_processing(now=self.now + 7)
            self.assertEqual(report.made_ready, 1)
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 7)["daily_used"], 1)
            new = dispatch.claim_next(blobs, now=self.now + 8, lease_seconds=2)
            self.assertEqual(new.envelope, envelope)
            self.assertEqual(new.attempt, 2)
            self.assertNotEqual(new.token, old.token)
            with self.assertRaises(DispatchLeaseConflict):
                dispatch.renew_lease(
                    envelope.job_id, OWNER, old.token, now=self.now + 9,
                )
            self.assertEqual(InputHandoff(dispatch, blobs).recover_processing(
                now=self.now + 9,
            ).examined, 0)

    def test_operator_resolution_rechecks_and_preserves_restored_file(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            envelope, _ = self.started_then_missing(dispatch, blobs)
            self.assertEqual(InputHandoff(dispatch, blobs).recover_processing(
                now=self.now + 35,
            ).needs_review, 1)
            self.restore(envelope)
            self.assertFalse(dispatch.resolve_expired_processing_review(
                OWNER, envelope.job_id, blobs, now=self.now + 36,
            ))
            self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "processing")
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 36)["daily_used"], 1)
            self.assertEqual(dispatch.claim_next(blobs, now=self.now + 37).attempt, 2)

    def test_active_lease_or_foreign_owner_cannot_be_reviewed(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            envelope, created = InputHandoff(dispatch, blobs).submit(
                OWNER, "a" * 64, "b" * 64, PDF,
                action="pdf:extract", suffix=".pdf", pages="1", now=self.now,
            )
            self.assertTrue(created)
            dispatch.claim_next(blobs, now=self.now + 1, lease_seconds=60)
            self.assertEqual(dispatch.pending_processing_inputs(now=self.now + 2), [])
            with self.assertRaises(JobNotFound):
                dispatch.inspect_expired_processing_input(
                    OWNER, envelope.job_id, blobs, now=self.now + 2,
                )
            with self.assertRaises(JobNotFound):
                dispatch.resolve_expired_processing_review(
                    FOREIGN, envelope.job_id, blobs, now=self.now + 62,
                )
            self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "processing")

    def test_cancellation_during_review_does_not_refund_twice(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            envelope, _ = self.started_then_missing(dispatch, blobs)
            self.assertEqual(InputHandoff(dispatch, blobs).recover_processing(
                now=self.now + 35,
            ).needs_review, 1)
            self.assertTrue(dispatch.cancel_dispatch(envelope.job_id, OWNER, now=self.now + 36))
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 36)["daily_used"], 0)
            self.assertEqual(InputHandoff(dispatch, blobs).recover_processing(
                now=self.now + 37,
            ).examined, 0)
            with self.assertRaises(JobNotFound):
                dispatch.resolve_expired_processing_review(
                    OWNER, envelope.job_id, blobs, now=self.now + 37,
                )

    def test_two_dispatch_connections_cannot_double_refund(self):
        with IntakeDispatchStore(self.db) as one, IntakeDispatchStore(self.db) as two, \
                PrivateBlobStore(self.root) as blobs:
            envelope, _ = self.started_then_missing(one, blobs)
            self.assertEqual(InputHandoff(one, blobs).recover_processing(
                now=self.now + 35,
            ).needs_review, 1)

            def resolve(dispatch):
                try:
                    return dispatch.resolve_expired_processing_review(
                        OWNER, envelope.job_id, blobs, now=self.now + 36,
                    )
                except (JobNotFound, JobStateError):
                    return "already-terminal"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(resolve, (one, two)))
            self.assertCountEqual(results, [True, "already-terminal"])
            self.assertEqual(one.usage_snapshot(OWNER, now=self.now + 37)["daily_used"], 0)
            self.assertEqual(one.get(envelope.job_id, OWNER).state, "failed")

    def test_invalid_batch_and_review_settings_are_rejected(self):
        with IntakeDispatchStore(self.db) as dispatch, PrivateBlobStore(self.root) as blobs:
            for limit in (0, -1, True, 101):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    dispatch.pending_processing_inputs(limit=limit)
            for interval in (0, -1, True, 3601):
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    InputHandoff(dispatch, blobs).recover_processing(
                        review_after_seconds=interval,
                    )


if __name__ == "__main__":
    unittest.main()
