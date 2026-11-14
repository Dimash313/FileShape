"""Executable adapter contracts for the first FileShape 5.0 module boundaries.

A runtime-checkable Protocol only checks attributes, not transaction semantics;
these tests also exercise the existing SQLite and in-process implementations.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from api.architecture_ports import (
    ArtifactReservationPort, ArtifactStoragePort, DispatchHandlePort,
    JobDispatchPort, JobMetadataPort,
)
from api.artifacts import ArtifactStore
from api.durable_jobs import DurableJobStore
from api.job_manager import JobManager
from api.jobs import JobNotFound


class MetadataContractTests(unittest.TestCase):
    def test_owner_isolation_and_atomic_reservation_refund(self):
        with DurableJobStore(":memory:") as store:
            self.assertIsInstance(store, JobMetadataPort)
            job = store.create(101, metered=True)
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 1)
            with self.assertRaises(JobNotFound):
                store.get(job.job_id, 202)
            self.assertTrue(store.discard_queued(job.job_id, 101))
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 0)
            with self.assertRaises(JobNotFound):
                store.get(job.job_id, 101)

    def test_idempotent_replay_does_not_charge_twice(self):
        with DurableJobStore(":memory:") as store:
            key_hash = "a" * 64
            fingerprint = "b" * 64
            original, created = store.create_idempotent(
                101, key_hash, fingerprint, metered=True,
            )
            self.assertTrue(created)
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 1)
            store.accept_admission(original.job_id, 101, key_hash)
            replay, created = store.create_idempotent(
                101, key_hash, fingerprint, metered=True,
            )
            self.assertFalse(created)
            self.assertEqual(replay.job_id, original.job_id)
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 1)
            store.transition(original.job_id, 101, "processing")
            store.transition(original.job_id, 101, "completed")
            self.assertEqual(store.usage_snapshot(101)["daily_used"], 1)


class DispatchContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_dispatcher_implements_contract(self):
        manager = JobManager(1, max_pending=1)
        self.addAsyncCleanup(manager.close)
        self.assertIsInstance(manager, JobDispatchPort)
        async def operation():
            await asyncio.sleep(0)
            return "ok"
        handle = manager.submit(operation)
        self.assertIsInstance(handle, DispatchHandlePort)
        self.assertEqual(await handle.result, "ok")
        await handle.finished
        self.assertTrue(handle.done)


class ArtifactContractTests(unittest.TestCase):
    def test_local_store_implements_private_reservation_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ArtifactStore(root, min_free_bytes=0)
            try:
                self.assertIsInstance(store, ArtifactStoragePort)
                job_id = "A" * 32
                item = store.reserve(job_id, 1024)
                self.assertIsInstance(item, ArtifactReservationPort)
                self.assertTrue(item.path.is_dir())
                with self.assertRaises(ValueError):
                    store.reserve(job_id, 1024)
                store.discard(job_id)
                self.assertFalse(item.path.exists())
            finally:
                store.close()
