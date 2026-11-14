"""Contract tests for the replaceable runtime metadata-store lifecycle."""
import tempfile
import unittest
from pathlib import Path

from api.job_runtime import JobRuntime


class FakeStore:
    def __init__(self, path):
        self.path = path
        self.events = []

    def discard_pending_admissions(self):
        self.events.append("discard")

    def mark_interrupted_failed(self):
        self.events.append("recover")

    def prune_terminal(self):
        self.events.append("prune")

    def close(self):
        self.events.append("close")


class RuntimeSeamTests(unittest.TestCase):
    def test_injected_store_receives_private_path_and_recovery_order(self):
        with tempfile.TemporaryDirectory() as directory:
            instances = []
            def factory(path):
                store = FakeStore(path)
                instances.append(store)
                return store
            runtime = JobRuntime(Path(directory) / "state", store_factory=factory)
            store = instances[0]
            self.assertEqual(store.path, Path(directory) / "state" / "jobs.sqlite3")
            self.assertEqual(store.events, ["discard", "recover", "prune"])
            runtime.close()
            self.assertEqual(store.events, ["discard", "recover", "prune", "close"])

    def test_second_owner_rejected_even_with_injected_store(self):
        with tempfile.TemporaryDirectory() as directory:
            first = JobRuntime(directory, store_factory=FakeStore)
            try:
                with self.assertRaisesRegex(RuntimeError, "Another API process"):
                    JobRuntime(directory, store_factory=FakeStore)
            finally:
                first.close()

    def test_failed_recovery_closes_store_and_releases_lock(self):
        class BrokenStore(FakeStore):
            def mark_interrupted_failed(self):
                raise RuntimeError("recovery failure")
        with tempfile.TemporaryDirectory() as directory:
            instances = []
            def broken(path):
                store = BrokenStore(path)
                instances.append(store)
                return store
            with self.assertRaisesRegex(RuntimeError, "recovery failure"):
                JobRuntime(directory, store_factory=broken)
            self.assertEqual(instances[0].events[-1], "close")
            runtime = JobRuntime(directory, store_factory=FakeStore)
            runtime.close()
