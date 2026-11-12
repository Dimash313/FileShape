"""SQLite job metadata persistence and privacy tests."""
import tempfile
import unittest
from pathlib import Path

from api.durable_jobs import DurableJobStore
from api.jobs import JobNotFound, JobStateError


class DurableJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "metadata.sqlite3"

    def test_reopen_preserves_terminal_metadata(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11)
            store.transition(job.job_id, 11, "processing")
            store.transition(job.job_id, 11, "completed")
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.get(job.job_id, 11).state, "completed")

    def test_owner_isolation_even_when_job_id_known(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11)
            with self.assertRaises(JobNotFound):
                store.get(job.job_id, 12)
            with self.assertRaises(JobNotFound):
                store.transition(job.job_id, 12, "failed")
            self.assertEqual(store.get(job.job_id, 11).state, "queued")

    def test_interrupted_jobs_are_failed_not_replayed(self):
        with DurableJobStore(self.path) as store:
            queued = store.create(11)
            running = store.create(11)
            completed = store.create(11)
            store.transition(running.job_id, 11, "processing")
            store.transition(completed.job_id, 11, "processing")
            store.transition(completed.job_id, 11, "completed")
        with DurableJobStore(self.path) as restarted:
            self.assertEqual(restarted.mark_interrupted_failed(), 2)
            self.assertEqual(restarted.get(queued.job_id, 11).state, "failed")
            self.assertEqual(restarted.get(running.job_id, 11).state, "failed")
            self.assertEqual(restarted.get(completed.job_id, 11).state, "completed")
            self.assertEqual(restarted.mark_interrupted_failed(), 0)

    def test_terminal_pruning_does_not_delete_active(self):
        with DurableJobStore(self.path) as store:
            active = store.create(11)
            failed = store.create(11)
            store.transition(failed.job_id, 11, "failed")
            self.assertEqual(store.prune_terminal(retention_seconds=0.00001), 1)
            self.assertEqual(store.get(active.job_id, 11).state, "queued")
            with self.assertRaises(JobNotFound):
                store.get(failed.job_id, 11)

    def test_invalid_transitions_and_no_sensitive_columns(self):
        with DurableJobStore(self.path) as store:
            job = store.create(11)
            with self.assertRaises(JobStateError):
                store.transition(job.job_id, 11, "completed")
            columns = {row[1] for row in store._db.execute("PRAGMA table_info(jobs)")}
            self.assertEqual(columns, {"job_id", "owner_id", "state", "created_at", "updated_at"})
            self.assertEqual(set(job.public()), {"job_id", "state", "created_at", "updated_at"})

    def test_invalid_owners_and_retention(self):
        with DurableJobStore(self.path) as store:
            for owner in (True, 0, -1, "11"):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    store.create(owner)
            with self.assertRaises(ValueError):
                store.prune_terminal(0)


if __name__ == "__main__":
    unittest.main()
