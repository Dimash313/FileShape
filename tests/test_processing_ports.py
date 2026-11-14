"""Behavioral contracts for the current processing adapters.

These checks do not prove distributed readiness; future adapters must satisfy
the same contracts plus restart, duplicate delivery and recovery scenarios.
"""
import asyncio
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

from api.artifacts import ArtifactStore
from api.durable_jobs import DurableJobStore, IdempotencyConflict
from api.job_manager import JobManager, ManagerClosed
from api.jobs import JobNotFound
from api.processing_ports import (
    ArtifactPort, ArtifactReservationPort, DispatcherPort,
    JobHandlePort, JobMetadataPort,
)


class MetadataPortTests(unittest.TestCase):
    def test_sqlite_adapter_owner_isolation_and_terminal_state(self):
        store = DurableJobStore(":memory:")
        try:
            self.assertIsInstance(store, JobMetadataPort)
            job = store.create(101)
            self.assertEqual(store.get(job.job_id, 101).state, "queued")
            with self.assertRaises(JobNotFound):
                store.get(job.job_id, 102)
            store.transition(job.job_id, 101, "processing")
            self.assertEqual(store.transition(job.job_id, 101, "completed").state, "completed")
            self.assertFalse(store.discard_queued(job.job_id, 102))
            self.assertEqual(store.get(job.job_id, 101).state, "completed")
        finally:
            store.close()

    def test_idempotent_admission_requires_same_owner_and_fingerprint(self):
        store = DurableJobStore(":memory:")
        try:
            key = hashlib.sha256(b"opaque-key").hexdigest()
            digest = hashlib.sha256(b"payload").hexdigest()
            job, created = store.create_idempotent(101, key, digest)
            self.assertTrue(created)
            store.accept_admission(job.job_id, 101, key)
            repeated, created = store.create_idempotent(101, key, digest)
            self.assertFalse(created)
            self.assertEqual(repeated.job_id, job.job_id)
            with self.assertRaises(IdempotencyConflict):
                store.create_idempotent(101, key, hashlib.sha256(b"other").hexdigest())
        finally:
            store.close()


class ArtifactPortTests(unittest.TestCase):
    def test_private_reservation_result_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(Path(root), max_bytes=32768, max_entries=3,
                                  min_free_bytes=0, ttl=60)
            try:
                self.assertIsInstance(store, ArtifactPort)
                job_id = secrets.token_urlsafe(24)
                reservation = store.reserve(job_id, 1024)
                self.assertIsInstance(reservation, ArtifactReservationPort)
                (reservation.path / "result.json").write_bytes(b'{"ok":true}')
                store.complete(job_id, "result.json", "application/json")
                lease, size, mime, filename = store.open_result(job_id)
                try:
                    self.assertEqual(lease.read(), b'{"ok":true}')
                    self.assertEqual(size, 11)
                    self.assertEqual(mime, "application/json")
                    self.assertEqual(filename, "result.json")
                finally:
                    lease.close()
                store.discard(job_id)
                self.assertFalse(reservation.path.exists())
            finally:
                store.close()


class DispatcherPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_dispatcher_handle_contract_and_shutdown(self):
        manager = JobManager(1, max_pending=1)
        try:
            self.assertIsInstance(manager, DispatcherPort)
            handle = manager.submit(lambda: asyncio.sleep(0, result="processed"))
            self.assertIsInstance(handle, JobHandlePort)
            self.assertEqual(await handle.result, "processed")
            await handle.finished
            self.assertTrue(handle.done)
        finally:
            await manager.close()
        with self.assertRaises(ManagerClosed):
            manager.submit(lambda: asyncio.sleep(0))
