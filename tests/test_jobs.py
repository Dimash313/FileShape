"""Security and lifecycle regression tests for future durable job metadata."""
import unittest
from unittest.mock import patch

from api.jobs import (
    JobCapacityExceeded, JobNotFound, JobRegistry, JobStateError,
)


class JobRegistryTests(unittest.TestCase):
    def test_valid_lifecycle_and_terminal_immutability(self):
        jobs = JobRegistry()
        created = jobs.create(101)
        self.assertEqual(created.state, "queued")
        self.assertGreaterEqual(len(created.job_id), 24)
        processing = jobs.transition(created.job_id, 101, "processing")
        self.assertEqual(processing.state, "processing")
        done = jobs.transition(created.job_id, 101, "completed")
        self.assertEqual(done.state, "completed")
        self.assertEqual(done.created_at, created.created_at)
        with self.assertRaises(JobStateError):
            jobs.transition(created.job_id, 101, "processing")

    def test_invalid_transitions_and_cancellation(self):
        jobs = JobRegistry()
        created = jobs.create(101)
        with self.assertRaises(JobStateError):
            jobs.transition(created.job_id, 101, "completed")
        jobs.transition(created.job_id, 101, "cancelled")
        with self.assertRaises(JobStateError):
            jobs.transition(created.job_id, 101, "processing")

    def test_owner_isolation_and_no_sensitive_public_metadata(self):
        jobs = JobRegistry()
        created = jobs.create(101)
        with self.assertRaises(JobNotFound):
            jobs.get(created.job_id, 102)
        with self.assertRaises(JobNotFound):
            jobs.transition(created.job_id, 102, "failed")
        with self.assertRaises(JobNotFound):
            jobs.get("does-not-exist", 101)
        self.assertEqual(set(created.public()), {
            "job_id", "state", "created_at", "updated_at",
        })
        self.assertNotIn("101", str(created.public()))

    def test_capacity_never_evicts_active_jobs(self):
        jobs = JobRegistry(max_entries=1)
        first = jobs.create(101)
        with self.assertRaises(JobCapacityExceeded):
            jobs.create(101)
        self.assertEqual(jobs.get(first.job_id, 101).state, "queued")

    def test_terminal_expiry_and_reclamation(self):
        with patch("api.jobs.time.time", return_value=1000):
            jobs = JobRegistry(max_entries=1, retention_seconds=60)
            created = jobs.create(101)
            jobs.transition(created.job_id, 101, "failed")
        with patch("api.jobs.time.time", return_value=1059):
            with self.assertRaises(JobCapacityExceeded):
                jobs.create(101)
        with patch("api.jobs.time.time", return_value=1060):
            second = jobs.create(101)
            self.assertNotEqual(created.job_id, second.job_id)
            with self.assertRaises(JobNotFound):
                jobs.get(created.job_id, 101)

    def test_shutdown_discards_metadata(self):
        jobs = JobRegistry()
        created = jobs.create(101)
        jobs.clear()
        with self.assertRaises(JobNotFound):
            jobs.get(created.job_id, 101)

    def test_reject_invalid_configuration_and_owner(self):
        with self.assertRaises(ValueError):
            JobRegistry(max_entries=0)
        with self.assertRaises(ValueError):
            JobRegistry(retention_seconds=0)
        for user_id in (0, -1, True, "123"):
            with self.subTest(user_id=user_id), self.assertRaises(ValueError):
                JobRegistry().create(user_id)


if __name__ == "__main__":
    unittest.main()
