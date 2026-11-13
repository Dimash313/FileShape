"""Stage 1 of v4.23: atomic opt-in job quota lifecycle and crash recovery.

Integration with all API/bot ingress paths is intentionally NOT enabled here.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from api.durable_jobs import DurableJobStore
from api.jobs import JobNotFound
from api.usage_ledger import OperationQuotaExceeded


class MeteredDurableJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "metered.sqlite3"

    def test_new_job_and_quota_are_created_atomically(self):
        with DurableJobStore(self.path) as store:
            jobs = [store.create(11, metered=True) for _ in range(10)]
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 10)
            self.assertEqual(len({job.job_id for job in jobs}), 10)
            with self.assertRaises(OperationQuotaExceeded):
                store.create(11, metered=True)
            self.assertEqual(store._db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 10)
            self.assertEqual(store.usage_snapshot(12)["daily_used"], 0)
            store.transition(jobs[0].job_id, 11, "failed")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 9)
            store.create(11, metered=True)
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 10)

    def test_completed_commits_once_and_not_released_on_replay(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11, metered=True)
            store.transition(job.job_id, 11, "processing")
            store.transition(job.job_id, 11, "completed")
            state = store._db.execute(
                "SELECT status FROM operation_usage WHERE operation_key=?",
                (store._job_operation_key(job.job_id),),
            ).fetchone()
            self.assertEqual(state, ("committed",))
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)
            with self.assertRaises(Exception):
                store.transition(job.job_id, 11, "failed")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)

    def test_failed_pack_operation_is_restored(self):
        with DurableJobStore(self.path) as store:
            store.grant_operation_pack(11, 10, "grant:pack:metered:0001")
            [store.create(11, metered=True) for _ in range(10)]
            job = store.create(11, metered=True)
            self.assertEqual(store.usage_snapshot(11)["pack_remaining"], 9)
            store.transition(job.job_id, 11, "cancelled")
            self.assertEqual(store.usage_snapshot(11)["pack_remaining"], 10)
            self.assertEqual(store.discard_queued(job.job_id, 11), False)

    def test_rejected_job_refunds_without_deleting_foreign_or_running(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11, metered=True)
            self.assertFalse(store.discard_queued(job.job_id, 12))
            self.assertTrue(store.discard_queued(job.job_id, 11))
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 0)
            with self.assertRaises(JobNotFound):
                store.get(job.job_id, 11)
            running = store.create(11, metered=True)
            store.transition(running.job_id, 11, "processing")
            self.assertFalse(store.discard_queued(running.job_id, 11))
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)

    def test_pending_idempotency_replay_and_crash_cleanup(self):
        key, fingerprint = "f" * 64, "d" * 64
        with DurableJobStore(self.path) as store:
            job, first = store.create_idempotent(11, key, fingerprint, metered=True)
            self.assertTrue(first)
            store.accept_admission(job.job_id, 11, key)
            repeated, second = store.create_idempotent(11, key, fingerprint, metered=True)
            self.assertFalse(second)
            self.assertEqual(job.job_id, repeated.job_id)
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)
        with DurableJobStore(self.path) as restarted:
            self.assertEqual(restarted.mark_interrupted_failed(), 1)
            self.assertEqual(restarted.usage_snapshot(11)["daily_used"], 0)
            self.assertEqual(restarted.get(job.job_id, 11).state, "failed")
            self.assertEqual(restarted.mark_interrupted_failed(), 0)

    def test_unaccepted_claim_is_refunded_on_restart(self):
        with DurableJobStore(self.path) as store:
            job, created = store.create_idempotent(11, "a" * 64, "b" * 64, metered=True)
            self.assertTrue(created)
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)
        with DurableJobStore(self.path) as restarted:
            self.assertEqual(restarted.discard_pending_admissions(), 1)
            self.assertEqual(restarted.usage_snapshot(11)["daily_used"], 0)
            self.assertEqual(restarted.discard_pending_admissions(), 0)
            with self.assertRaises(JobNotFound):
                restarted.get(job.job_id, 11)

    def test_transition_rolls_back_state_if_settlement_fails(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11, metered=True)
            with patch.object(store, "_settle_operation_in_transaction",
                              side_effect=sqlite3.OperationalError("injected")):
                with self.assertRaises(sqlite3.OperationalError):
                    store.transition(job.job_id, 11, "failed")
            self.assertEqual(store.get(job.job_id, 11).state, "queued")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 1)
            store.transition(job.job_id, 11, "failed")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 0)

    def test_cross_connection_atomic_quotas(self):
        with DurableJobStore(self.path) as first, DurableJobStore(self.path) as second:
            def create(i):
                try:
                    (first if i % 2 else second).create(11, metered=True)
                    return True
                except OperationQuotaExceeded:
                    return False
            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(create, range(25)))
            self.assertEqual(sum(outcomes), 10)
            self.assertEqual(first.usage_snapshot(11)["daily_used"], 10)
            self.assertEqual(first._db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 10)

    def test_legacy_job_is_never_billed(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11)
            store.transition(job.job_id, 11, "processing")
            store.transition(job.job_id, 11, "completed")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 0)
            with self.assertRaises(ValueError):
                store.create(11, metered="true")
            self.assertEqual(store.usage_snapshot(11)["daily_used"], 0)


if __name__ == "__main__":
    unittest.main()
