"""Regression tests for offline result availability and quota reconciliation."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest

from api.fenced_results import FencedDispatchStore, FencedResultGate
from api.private_blob_store import BlobUnavailable, PrivateBlobStore
from api.result_recovery import ResultRecovery
from api.usage_ledger import MAX_PACK_BALANCE


OWNER = 101


class ResultRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs_path = Path(self.temp.name) / "jobs.sqlite3"
        self.blobs_path = Path(self.temp.name) / "blob"
        self.now = time.time()

    def stores(self):
        return FencedDispatchStore(self.jobs_path), PrivateBlobStore(self.blobs_path)

    def approve(self, dispatch, blobs, *, key="a" * 64, blob_ttl=600):
        input_ref = blobs.stage_input(OWNER, b"uploaded PDF", now=self.now)
        envelope, created = dispatch.admit_staged_single(
            OWNER, key, "b" * 64, input_ref=input_ref,
            result_ref=secrets.token_urlsafe(24),
            action="pdf:extract", suffix=".pdf", pages="1",
            now=self.now,
        )
        self.assertTrue(created)
        blobs.bind_input(OWNER, envelope.job_id, input_ref, now=self.now)
        lease = dispatch.claim_next(now=self.now + 1)
        data = b"private result bytes"
        candidate = blobs.stage_candidate(
            OWNER, envelope.job_id, data, now=self.now + 2, ttl=blob_ttl,
        )
        gate = FencedResultGate(dispatch, blobs)
        gate.approve(
            OWNER, envelope.job_id, lease.token, candidate, now=self.now + 3,
        )
        return envelope, candidate

    def snapshot(self, dispatch, job_id):
        return dispatch._db.execute(
            """SELECT status,compensation,first_missing_at,confirmed_at,
                      available_until FROM result_delivery_state WHERE job_id=?""",
            (job_id,),
        ).fetchone()

    def test_premature_missing_blob_detected_twice_and_daily_credit_once(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                envelope, candidate = self.approve(dispatch, blobs)
                gate = FencedResultGate(dispatch, blobs)
                recovery = ResultRecovery(dispatch, blobs)
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 4,
                )["daily_used"], 1)
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("available", "none"))
                self.assertTrue(blobs.delete(OWNER, candidate, job_id=envelope.job_id))
                first = recovery.reconcile(now=self.now + 5)
                self.assertEqual((first.suspected, first.credited), (1, 0))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0], "suspect")
                early = recovery.reconcile(now=self.now + 10)
                self.assertEqual(early.confirmed_lost, 0)
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 11,
                )["daily_used"], 1)
                second = recovery.reconcile(now=self.now + 36)
                self.assertEqual((second.confirmed_lost, second.credited), (1, 1))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("lost", "credited"))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 36,
                )["daily_used"], 0)
                self.assertEqual(dispatch.get(envelope.job_id, OWNER).state, "completed")
                with self.assertRaises(BlobUnavailable):
                    gate.read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 37,
                    )
                self.assertEqual(recovery.reconcile(now=self.now + 38).credited, 0)
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 38,
                )["daily_used"], 0)
        with FencedDispatchStore(self.jobs_path) as reopened:
            self.assertEqual(self.snapshot(reopened, envelope.job_id)[0:2],
                             ("lost", "credited"))
            self.assertEqual(reopened.usage_snapshot(
                OWNER, now=self.now + 40,
            )["daily_used"], 0)

    def test_transient_corruption_then_recovery_never_credits(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                envelope, candidate = self.approve(dispatch, blobs)
                recovery = ResultRecovery(dispatch, blobs)
                path = self.blobs_path / candidate
                path.write_bytes(b"corrupt result byte")
                self.assertEqual(recovery.reconcile(now=self.now + 5).suspected, 1)
                path.write_bytes(b"private result bytes")
                healed = recovery.reconcile(now=self.now + 36)
                self.assertEqual((healed.recovered, healed.credited), (1, 0))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("available", "none"))
                self.assertIsNone(self.snapshot(dispatch, envelope.job_id)[2])
                self.assertEqual(
                    FencedResultGate(dispatch, blobs).read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 37,
                    ), b"private result bytes",
                )
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 37,
                )["daily_used"], 1)

    def test_normal_expiry_does_not_trigger_credit(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                envelope, candidate = self.approve(dispatch, blobs, blob_ttl=5)
                recovery = ResultRecovery(dispatch, blobs)
                self.assertEqual(
                    self.snapshot(dispatch, envelope.job_id)[4], self.now + 7,
                )
                report = recovery.reconcile(now=self.now + 10)
                self.assertEqual((report.expired, report.credited), (1, 0))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("expired", "none"))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 10,
                )["daily_used"], 1)
                with self.assertRaises(BlobUnavailable):
                    FencedResultGate(dispatch, blobs).read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 10,
                    )

    def test_suspect_at_expiry_requires_review_not_automatic_refund(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                envelope, candidate = self.approve(dispatch, blobs, blob_ttl=50)
                recovery = ResultRecovery(dispatch, blobs)
                (self.blobs_path / candidate).unlink()
                self.assertEqual(recovery.reconcile(now=self.now + 5).suspected, 1)
                report = recovery.reconcile(now=self.now + 55)
                self.assertEqual((report.manual_review, report.credited), (1, 0))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("review", "none"))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 55,
                )["daily_used"], 1)

    def test_pack_credit_defers_when_balance_full_and_retries_safely(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                dispatch.grant_operation_pack(
                    OWNER, 10, "trusted:pack:recovery-test", now=self.now,
                )
                # Spend all ten daily allowances so next operation uses pack.
                for i in range(10):
                    self.approve(dispatch, blobs, key=f"{i:064x}")
                envelope, candidate = self.approve(dispatch, blobs, key="f" * 64)
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 4,
                )["pack_remaining"], 9)
                operation_key = dispatch._job_operation_key(envelope.job_id)
                self.assertEqual(dispatch._db.execute(
                    "SELECT source FROM operation_usage WHERE operation_key=?",
                    (operation_key,),
                ).fetchone()[0], "pack")
                # Simulate later purchases filling available pack capacity.
                dispatch._db.execute(
                    "UPDATE operation_pack_balances SET balance=? WHERE owner_id=?",
                    (MAX_PACK_BALANCE, OWNER),
                )
                recovery = ResultRecovery(dispatch, blobs)
                blobs.delete(OWNER, candidate, job_id=envelope.job_id)
                recovery.reconcile(now=self.now + 5)
                blocked = recovery.reconcile(now=self.now + 36)
                self.assertEqual((blocked.confirmed_lost, blocked.pending_credit), (1, 1))
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("lost", "pending"))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 36,
                )["pack_remaining"], MAX_PACK_BALANCE)
                dispatch._db.execute(
                    "UPDATE operation_pack_balances SET balance=? WHERE owner_id=?",
                    (MAX_PACK_BALANCE - 1, OWNER),
                )
                credited = recovery.reconcile(now=self.now + 37)
                self.assertEqual((credited.credited, credited.pending_credit), (1, 0))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 37,
                )["pack_remaining"], MAX_PACK_BALANCE)
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0:2],
                                 ("lost", "credited"))
                self.assertEqual(recovery.reconcile(now=self.now + 38).credited, 0)

    def test_pack_credit_preserves_other_active_reservation_headroom(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                dispatch.grant_operation_pack(
                    OWNER, 10, "trusted:pack:headroom-test", now=self.now,
                )
                for i in range(10):
                    self.approve(dispatch, blobs, key=f"{i:064x}")
                lost, lost_candidate = self.approve(
                    dispatch, blobs, key="e" * 64,
                )
                # Another accepted pack-funded job may still fail and have
                # its *own* reserved operation returned to the pack.
                input_ref = blobs.stage_input(
                    OWNER, b"next upload", now=self.now + 4,
                )
                waiting, created = dispatch.admit_staged_single(
                    OWNER, "d" * 64, "c" * 64, input_ref=input_ref,
                    result_ref=secrets.token_urlsafe(24),
                    action="pdf:extract", suffix=".pdf", pages="1",
                    now=self.now + 4,
                )
                self.assertTrue(created)
                blobs.bind_input(
                    OWNER, waiting.job_id, input_ref, now=self.now + 4,
                )
                dispatch._db.execute(
                    "UPDATE operation_pack_balances SET balance=? WHERE owner_id=?",
                    (MAX_PACK_BALANCE - 1, OWNER),
                )
                recovery = ResultRecovery(dispatch, blobs)
                blobs.delete(OWNER, lost_candidate, job_id=lost.job_id)
                recovery.reconcile(now=self.now + 5)
                report = recovery.reconcile(now=self.now + 36)
                self.assertEqual((report.confirmed_lost, report.pending_credit),
                                 (1, 1))
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 36,
                )["pack_remaining"], MAX_PACK_BALANCE - 1)
                # Settle the other reservation successfully. Its failure
                # headroom is no longer needed, allowing exactly one credit.
                lease = dispatch.claim_next(now=self.now + 37)
                self.assertEqual(lease.envelope.job_id, waiting.job_id)
                candidate = blobs.stage_candidate(
                    OWNER, waiting.job_id, b"other successful result",
                    now=self.now + 38,
                )
                FencedResultGate(dispatch, blobs).approve(
                    OWNER, waiting.job_id, lease.token, candidate,
                    now=self.now + 39,
                )
                credited = recovery.reconcile(now=self.now + 40)
                self.assertEqual(credited.credited, 1)
                self.assertEqual(dispatch.usage_snapshot(
                    OWNER, now=self.now + 40,
                )["pack_remaining"], MAX_PACK_BALANCE)
                self.assertEqual(recovery.reconcile(now=self.now + 41).credited, 0)

    def test_two_connections_do_not_double_credit_a_lost_job(self):
        with FencedDispatchStore(self.jobs_path) as first:
            with FencedDispatchStore(self.jobs_path) as second:
                with PrivateBlobStore(self.blobs_path) as blobs:
                    envelope, candidate = self.approve(first, blobs)
                    blobs.delete(OWNER, candidate, job_id=envelope.job_id)
                    ResultRecovery(first, blobs).reconcile(now=self.now + 5)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = list(pool.map(
                            lambda rec: rec.reconcile(now=self.now + 40),
                            (ResultRecovery(first, blobs), ResultRecovery(second, blobs)),
                        ))
                    self.assertEqual(sum(x.credited for x in results), 1)
                    self.assertEqual(first.usage_snapshot(
                        OWNER, now=self.now + 40,
                    )["daily_used"], 0)
                    self.assertEqual(first._db.execute(
                        "SELECT count(*) FROM operation_usage WHERE status='released'",
                    ).fetchone()[0], 1)

    def test_invalid_recovery_configuration_fails_closed(self):
        with FencedDispatchStore(self.jobs_path) as dispatch:
            with PrivateBlobStore(self.blobs_path) as blobs:
                recovery = ResultRecovery(dispatch, blobs)
                envelope, candidate = self.approve(dispatch, blobs)
                for options in (
                    {"limit": 0}, {"limit": True}, {"limit": 101},
                    {"confirm_after_seconds": 0}, {"confirm_after_seconds": 1.0},
                    {"confirm_after_seconds": True},
                    {"now": True}, {"now": float("nan")},
                ):
                    with self.subTest(options=options), self.assertRaises(ValueError):
                        recovery.reconcile(**options)
                self.assertEqual(self.snapshot(dispatch, envelope.job_id)[0], "available")
                self.assertEqual(
                    FencedResultGate(dispatch, blobs).read_approved(
                        OWNER, envelope.job_id, envelope.result_ref,
                        now=self.now + 4,
                    ), b"private result bytes",
                )
