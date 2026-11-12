"""SQLite job metadata persistence and privacy tests."""
import os
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

    def test_stale_concurrent_transition_is_rejected(self):
        # Two separate connections see the same queued state. Only one may
        # commit a transition; the other must not overwrite the winner.
        with DurableJobStore(self.path) as first, DurableJobStore(self.path) as second:
            job = first.create(11)
            stale = second.get(job.job_id, 11)
            self.assertEqual(stale.state, "queued")
            first.transition(job.job_id, 11, "processing")
            with self.assertRaises(JobStateError):
                second.transition(job.job_id, 11, "cancelled")
            self.assertEqual(first.get(job.job_id, 11).state, "processing")

    @unittest.skipUnless(os.name == "posix", "POSIX file modes only")
    def test_database_file_is_private(self):
        with DurableJobStore(self.path) as store:
            store.create(11)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        os.chmod(self.path, 0o644)
        with DurableJobStore(self.path):
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_reject_symlink_database(self):
        target = Path(self.tmp.name) / "real.sqlite3"
        target.write_bytes(b"")
        link = Path(self.tmp.name) / "link.sqlite3"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):
            DurableJobStore(link)

    def test_invalid_owners_and_retention(self):
        with DurableJobStore(self.path) as store:
            for owner in (True, 0, -1, "11"):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    store.create(owner)
            with self.assertRaises(ValueError):
                store.prune_terminal(0)


if __name__ == "__main__":
    unittest.main()
