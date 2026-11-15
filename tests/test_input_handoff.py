"""Offline crash / idempotency / ownership gates for input handoff.

These assertions do not imply that the live API is distributed or uses the
IntakeDispatchStore. Only a future authenticated server adapter may call it.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import secrets
import tempfile
import time
import unittest

from api.durable_jobs import IdempotencyConflict
from api.fenced_results import FencedResultGate
from api.input_handoff import InputHandoff, IntakeDispatchStore
from api.jobs import JobNotFound, JobStateError
from api.private_blob_store import BlobUnavailable, PrivateBlobStore
from api.job_envelope import JobEnvelopeError


OWNER = 101
OTHER = 202
PDF = b"%PDF-1.4\nvalidating staged bytes independently"


class InputHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "jobs.sqlite3"
        self.blob_root = Path(self.tmp.name) / "private"
        self.now = time.time()

    def stores(self):
        return IntakeDispatchStore(self.db_path), PrivateBlobStore(self.blob_root)

    def submit(self, intake, *, key="a" * 64, fingerprint="b" * 64, owner=OWNER):
        return intake.submit(
            owner, key, fingerprint, PDF,
            action="pdf:extract", suffix=".pdf", pages="1",
            now=self.now,
        )

    def simulate_partial_admission(self, dispatch, blobs, *, owner=OWNER, key="a" * 64):
        staged = blobs.stage_input(owner, PDF, now=self.now)
        envelope, created = dispatch.admit_staged_single(
            owner, key, "b" * 64, input_ref=staged,
            result_ref=secrets.token_urlsafe(24),
            action="pdf:extract", suffix=".pdf", pages="1",
            now=self.now,
        )
        self.assertTrue(created)
        return envelope

    def test_submit_verified_then_claim_and_approve(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            intake = InputHandoff(dispatch, blobs)
            env, created = self.submit(intake)
            self.assertTrue(created)
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "ready")
            self.assertEqual(blobs.read_input(
                OWNER, env.job_id, env.input_ref, now=self.now + 1,
            ), PDF)
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now)["daily_used"], 1)
            lease = dispatch.claim_next(now=self.now + 1)
            self.assertEqual(lease.envelope, env)
            candidate = blobs.stage_candidate(
                OWNER, env.job_id, b"result content", now=self.now + 2,
            )
            FencedResultGate(dispatch, blobs).approve(
                OWNER, env.job_id, lease.token, candidate, now=self.now + 3,
            )
            self.assertEqual(dispatch.get(env.job_id, OWNER).state, "completed")
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 3)["daily_used"], 1)

    def test_crash_after_admission_before_bind_is_resumable(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            self.assertIsNone(dispatch.claim_next(now=self.now + 1))
            self.assertEqual(dispatch.pending_inputs(), [(OWNER, env)])
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 1)["daily_used"], 1)
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            recovered = InputHandoff(dispatch, blobs).recover(now=self.now + 2)
            self.assertEqual((recovered.examined, recovered.made_ready), (1, 1))
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "ready")
            self.assertEqual(blobs.read_input(
                OWNER, env.job_id, env.input_ref, now=self.now + 3,
            ), PDF)
            self.assertEqual(dispatch.claim_next(now=self.now + 3).envelope, env)
            self.assertEqual(InputHandoff(dispatch, blobs).recover(
                now=self.now + 4,
            ).examined, 0)

    def test_crash_after_bind_before_ready_can_recover(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            self.assertTrue(blobs.bind_input(OWNER, env.job_id, env.input_ref, now=self.now))
            self.assertIsNone(dispatch.claim_next(now=self.now + 1))
            report = InputHandoff(dispatch, blobs).recover(now=self.now + 2)
            self.assertEqual(report.made_ready, 1)
            self.assertEqual(dispatch.claim_next(now=self.now + 3).envelope, env)

    def test_duplicate_submissions_create_one_accepted_job(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            intake = InputHandoff(dispatch, blobs)
            original, created = self.submit(intake)
            same, replay_created = self.submit(intake)
            self.assertTrue(created)
            self.assertFalse(replay_created)
            self.assertEqual(same, original)
            self.assertEqual(dispatch._db.execute(
                "SELECT count(*) FROM jobs",
            ).fetchone()[0], 1)
            self.assertEqual(blobs._db.execute(
                "SELECT COUNT(*) FROM staged_blobs",
            ).fetchone()[0], 1)
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now)["daily_used"], 1)
            with self.assertRaises(IdempotencyConflict):
                self.submit(intake, fingerprint="c" * 64)
            self.assertEqual(blobs._db.execute(
                "SELECT COUNT(*) FROM staged_blobs",
            ).fetchone()[0], 1)
            lease = dispatch.claim_next(now=self.now + 1)
            repeated, created = self.submit(intake)
            self.assertFalse(created)
            self.assertEqual(repeated, original)
            self.assertEqual(dispatch.get(original.job_id, OWNER).state, "processing")
            self.assertTrue(dispatch.settle_lease(
                original.job_id, OWNER, lease.token, success=False, now=self.now + 2,
            ))
            repeated, created = self.submit(intake)
            self.assertFalse(created)
            self.assertEqual(repeated, original)
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 3)["daily_used"], 0)

    def test_missing_foreign_input_is_never_bound_or_claimable(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            foreign = blobs.stage_input(OTHER, PDF, now=self.now)
            env, _ = dispatch.admit_staged_single(
                OWNER, "a" * 64, "b" * 64, input_ref=foreign,
                result_ref=secrets.token_urlsafe(24),
                action="pdf:extract", suffix=".pdf", pages="1", now=self.now,
            )
            result = InputHandoff(dispatch, blobs).recover(now=self.now + 2)
            self.assertEqual(result.suspected, 1)
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "suspect")
            self.assertIsNone(dispatch.claim_next(now=self.now + 3))
            result = InputHandoff(dispatch, blobs).recover(now=self.now + 34)
            self.assertEqual(result.needs_review, 1)
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "review")
            with self.assertRaises(JobNotFound):
                dispatch.input_status(OTHER, env.job_id)
            self.assertTrue(dispatch.fail_reviewed_input(
                OWNER, env.job_id, blobs, now=self.now + 35,
            ))
            self.assertEqual(dispatch.get(env.job_id, OWNER).state, "failed")
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 35)["daily_used"], 0)
            self.assertEqual(blobs._db.execute(
                "SELECT owner_id FROM staged_blobs WHERE ref=?", (foreign,),
            ).fetchone()[0], OTHER)
            self.assertIsNone(dispatch.claim_next(now=self.now + 36))
            with self.assertRaises((JobNotFound, JobStateError)):
                dispatch.fail_reviewed_input(OWNER, env.job_id, blobs, now=self.now + 36)

    def test_missing_input_can_be_restored_after_suspicion(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            path = self.blob_root / env.input_ref
            path.unlink()
            self.assertEqual(InputHandoff(dispatch, blobs).recover(
                now=self.now + 2,
            ).suspected, 1)
            self.assertIsNone(dispatch.claim_next(now=self.now + 3))
            path.write_bytes(PDF)
            path.chmod(0o600)
            self.assertEqual(InputHandoff(dispatch, blobs).recover(
                now=self.now + 40,
            ).made_ready, 1)
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "ready")
            self.assertEqual(dispatch.claim_next(now=self.now + 41).envelope, env)

    def test_operator_review_refuses_failure_if_input_recovered(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            path = self.blob_root / env.input_ref
            path.unlink()
            rec = InputHandoff(dispatch, blobs)
            self.assertEqual(rec.recover(now=self.now + 2).suspected, 1)
            self.assertEqual(rec.recover(now=self.now + 40).needs_review, 1)
            path.write_bytes(PDF)
            path.chmod(0o600)
            self.assertFalse(dispatch.fail_reviewed_input(
                OWNER, env.job_id, blobs, now=self.now + 45,
            ))
            self.assertEqual(dispatch.input_status(OWNER, env.job_id)[1], "ready")
            self.assertEqual(dispatch.get(env.job_id, OWNER).state, "queued")
            self.assertEqual(dispatch.claim_next(now=self.now + 46).envelope, env)

    def test_cancelled_handoff_not_resurrected(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            self.assertTrue(dispatch.cancel_dispatch(env.job_id, OWNER, now=self.now + 1))
            self.assertEqual(InputHandoff(dispatch, blobs).recover(
                now=self.now + 2,
            ).examined, 0)
            with self.assertRaises(JobNotFound):
                dispatch.mark_input_ready(
                    OWNER, env.job_id, env.input_ref, blobs, now=self.now + 3,
                )
            self.assertIsNone(dispatch.claim_next(now=self.now + 4))
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now + 4)["daily_used"], 0)

    def test_concurrent_claims_and_recovery_are_isolated(self):
        with IntakeDispatchStore(self.db_path) as one, \
                IntakeDispatchStore(self.db_path) as two, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(one, blobs)
            # Multiple workers see no work before readiness.
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda x: x.claim_next(now=self.now + 1),
                    (one, two),
                ))
            self.assertEqual(results, [None, None])
            with ThreadPoolExecutor(max_workers=2) as pool:
                recovered = list(pool.map(
                    lambda d: InputHandoff(d, blobs).recover(now=self.now + 2),
                    (one, two),
                ))
            self.assertIn(sum(x.made_ready for x in recovered), (1, 2))
            self.assertEqual(one.input_status(OWNER, env.job_id)[1], 'ready')
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda x: x.claim_next(now=self.now + 3),
                    (one, two),
                ))
            claimed = [x for x in results if x is not None]
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0].envelope, env)
            self.assertEqual(one.usage_snapshot(OWNER, now=self.now + 3)["daily_used"], 1)

    def test_rejected_admission_cleans_staged_input_and_never_charges(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            intake = InputHandoff(dispatch, blobs)
            with self.assertRaises(JobEnvelopeError):
                intake.submit(
                    OWNER, "a" * 64, "b" * 64, PDF,
                    action="unsafe:execute", suffix=".pdf", now=self.now,
                )
            self.assertEqual(blobs._db.execute(
                "SELECT COUNT(*) FROM staged_blobs",
            ).fetchone()[0], 0)
            self.assertEqual(dispatch._db.execute(
                "SELECT COUNT(*) FROM jobs",
            ).fetchone()[0], 0)
            self.assertEqual(dispatch.usage_snapshot(OWNER, now=self.now)["daily_used"], 0)

    def test_invalid_handoff_inputs_rejected(self):
        with IntakeDispatchStore(self.db_path) as dispatch, \
                PrivateBlobStore(self.blob_root) as blobs:
            env = self.simulate_partial_admission(dispatch, blobs)
            # An outbox reference alone is not proof of staged content.
            # Directly marking an unbound input as ready must fail.
            with self.assertRaises(BlobUnavailable):
                dispatch.mark_input_ready(
                    OWNER, env.job_id, env.input_ref, blobs, now=self.now,
                )
            with self.assertRaises(BlobUnavailable):
                dispatch.mark_input_ready(
                    OWNER, env.job_id, "x" * 32, blobs, now=self.now,
                )
            with self.assertRaises(JobNotFound):
                dispatch.mark_input_ready(
                    OTHER, env.job_id, env.input_ref, blobs, now=self.now,
                )
            for limit in (0, True, -1, 101):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    dispatch.pending_inputs(limit=limit)
            for interval in (0, True, -1, 3601):
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    InputHandoff(dispatch, blobs).recover(
                        now=self.now, review_after_seconds=interval,
                    )
            self.assertIsNone(dispatch.claim_next(now=self.now + 1))
