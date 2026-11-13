"""Known finished-job metadata repair without replay or touching unrelated jobs."""
import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from api.artifacts import ArtifactStore
from api.background_jobs import BackgroundJobs
from api.durable_jobs import DurableJobStore
from api.job_manager import JobManager, ManagerFull
from api.jobs import JobCapacityExceeded
from api.worker_runner import WorkerFailed

OWNER = 12345
KEY = "reconciliation_key_0001"
NEXT_KEY = "reconciliation_key_0002"


class ReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = DurableJobStore(root / "jobs.sqlite3")
        self.artifacts = ArtifactStore(root / "artifacts")
        self.manager = JobManager(1)
        self.calls = []
        async def worker(payload):
            self.calls.append(payload["operation"])
            return {"ok": True} if payload["operation"] == "validate_only" else {"ok": True, "info": {"lines": 1}}
        self.service = BackgroundJobs(self.store, self.manager, self.artifacts, worker, 1024, 1024)

    async def asyncTearDown(self):
        try:
            await self.manager.close()
            self.service.close()
        finally:
            self.store.close()
            self.tmp.cleanup()

    async def create(self, key=None, data=b"input"):
        upload = UploadFile(file=BytesIO(data), filename="input.txt")
        return await self.service.create(upload, "txt:info", ".txt", "", OWNER, idempotency_key=key)

    async def settled(self, job_id):
        async with asyncio.timeout(3):
            while job_id in self.service.handles:
                await asyncio.sleep(0.001)

    async def block_worker(self):
        release = asyncio.Event()
        blocker = self.manager.submit(release.wait)
        async with asyncio.timeout(3):
            while self.manager.active != 1:
                await asyncio.sleep(0.001)
        return release, blocker

    async def queued(self, key=None):
        with patch.object(self.manager, "run", new=AsyncMock(return_value={"ok": True})):
            return await self.create(key)

    async def cancel_with_metadata_outage(self, job_id):
        handle = self.service.handles[job_id]
        with patch.object(self.store, "get", side_effect=sqlite3.OperationalError("temporary failure")):
            await handle.cancel()
            self.service._settled(job_id, OWNER, handle)
        await self.settled(job_id)

    def late_cancel_with_metadata_outage(self, job_id):
        future = asyncio.get_running_loop().create_future()
        future.cancel()
        handle = SimpleNamespace(result=future, done=True)
        self.service.handles[job_id] = handle
        self.service.owners[job_id] = OWNER
        with patch.object(self.store, "get", side_effect=sqlite3.OperationalError("temporary failure")):
            self.service._settled(job_id, OWNER, handle)

    def pending_terminal(self, state="failed", owner=OWNER):
        item = self.store.create(owner)
        self.service._tracked.add(item.job_id)
        self.service._pending_terminal[item.job_id] = (owner, state)
        return item

    async def test_opt_in_metered_background_job_commits_and_replay_is_free(self):
        upload = UploadFile(file=BytesIO(b"hello"), filename="input.txt")
        with patch.object(self.manager, "run", new=AsyncMock(return_value={"ok": True})):
            job = await self.service.create(
                upload, "txt:info", ".txt", "", OWNER,
                idempotency_key=KEY, metered=True,
            )
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)
        await self.settled(job.job_id)
        self.assertEqual(self.store.get(job.job_id, OWNER).state, "completed")
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)
        again = await self.service.create(
            UploadFile(file=BytesIO(b"hello"), filename="input.txt"),
            "txt:info", ".txt", "", OWNER, idempotency_key=KEY, metered=True,
        )
        self.assertEqual(again.job_id, job.job_id)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)

    async def test_opt_in_metered_background_validation_failure_refunds(self):
        with patch.object(self.manager, "run", new=AsyncMock(side_effect=WorkerFailed("bad input"))):
            with self.assertRaises(WorkerFailed):
                await self.service.create(
                    UploadFile(file=BytesIO(b"hello"), filename="input.txt"),
                    "txt:info", ".txt", "", OWNER, metered=True,
                )
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 0)

    async def test_queued_cancel_metadata_recovers_without_replaying_work(self):
        release, blocker = await self.block_worker()
        try:
            item = await self.queued()
            artifact = self.artifacts._entries[item.job_id]
            await self.cancel_with_metadata_outage(item.job_id)
            self.assertFalse(artifact.path.exists())
            self.assertEqual(self.artifacts.reserved_bytes, 0)
            self.assertEqual(self.store.get(item.job_id, OWNER).state, "queued")
            self.assertEqual(self.service.pending_count, 1)
            self.assertEqual(self.service.tracked_count, 1)
            self.assertNotIn(item.job_id, self.service.active_ids)
            self.assertEqual(self.service.reconcile(), 1)
            self.assertEqual(self.store.get(item.job_id, OWNER).state, "cancelled")
            self.assertEqual(self.service.pending_count, 0)
            self.assertEqual(self.service.tracked_count, 0)
            self.assertEqual(self.calls, [])
            self.assertEqual(self.service.reconcile(), 0)
        finally:
            release.set()
            await blocker.wait()

    async def test_running_failure_repairs_metadata_after_database_recovers(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        async def worker(payload):
            self.calls.append(payload["operation"])
            if payload["operation"] == "single":
                entered.set()
                await release.wait()
                raise WorkerFailed("private worker details")
            return {"ok": True}
        self.service.worker = worker
        item = await self.create()
        await asyncio.wait_for(entered.wait(), 3)
        with patch.object(self.store, "get", side_effect=sqlite3.OperationalError("temporary failure")):
            release.set()
            await self.settled(item.job_id)
        self.assertEqual(self.store.get(item.job_id, OWNER).state, "processing")
        self.assertEqual(self.service.reconcile(), 1)
        self.assertEqual(self.store.get(item.job_id, OWNER).state, "failed")
        self.assertEqual(self.calls, ["validate_only", "single"])
        self.assertEqual(self.artifacts.reserved_bytes, 0)

    async def test_late_cancel_reconciliation_preserves_completed_result(self):
        item = await self.create(KEY)
        await self.settled(item.job_id)
        self.assertEqual(self.store.get(item.job_id, OWNER).state, "completed")
        self.late_cancel_with_metadata_outage(item.job_id)
        self.assertEqual(self.service.pending_count, 1)
        before, *_ = self.artifacts.open_result(item.job_id)
        with before:
            content = before.read()
        self.assertEqual(self.service.reconcile(), 1)
        self.assertEqual(self.store.get(item.job_id, OWNER).state, "completed")
        after, *_ = self.artifacts.open_result(item.job_id)
        with after:
            self.assertEqual(after.read(), content)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.calls, ["validate_only", "single"])

    async def test_reconcile_drops_missing_owned_record_and_preserves_foreign_and_legacy_work(self):
        item = self.pending_terminal()
        self.store.discard_queued(item.job_id, OWNER)
        legacy = self.store.create(OWNER)
        foreign = self.store.create(99)
        self.store.transition(foreign.job_id, 99, "processing")
        self.service._tracked.add(foreign.job_id)
        self.service._pending_terminal[foreign.job_id] = (OWNER, "cancelled")
        self.assertEqual(self.service.reconcile(), 2)
        self.assertEqual(self.service.pending_count, 0)
        self.assertEqual(self.store.get(legacy.job_id, OWNER).state, "queued")
        self.assertEqual(self.store.get(foreign.job_id, 99).state, "processing")

    async def test_reconcile_budget_and_first_database_error_bound_work(self):
        items = [self.pending_terminal() for _ in range(7)]
        self.assertEqual(self.service.reconcile(max_updates=2), 2)
        self.assertEqual(self.service.pending_count, 5)
        for item in items[:2]:
            self.assertEqual(self.store.get(item.job_id, OWNER).state, "failed")
        with patch.object(self.store, "get", side_effect=sqlite3.OperationalError("temporary failure")) as read:
            self.assertEqual(self.service.reconcile(), 0)
            self.assertEqual(read.call_count, 1)
        self.assertEqual(self.service.pending_count, 5)
        self.assertEqual(self.service.reconcile(), 5)
        for value in (0, -1, 1001, True):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                self.service.reconcile(value)

    async def test_tracking_covers_preparation_and_rejects_new_claims_when_full(self):
        self.store.max_entries = 1
        entered = asyncio.Event()
        release = asyncio.Event()
        original_worker = self.service.worker
        async def worker(payload):
            if payload["operation"] == "validate_only":
                entered.set()
                await release.wait()
            return await original_worker(payload)
        self.service.worker = worker
        first = asyncio.create_task(self.create(KEY))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            self.assertEqual(self.service.tracked_count, 1)
            self.assertEqual(len(self.service.active_ids), 1)
            self.assertEqual(self.service.handles, {})
            with self.assertRaises(HTTPException) as rejected:
                await self.create(NEXT_KEY)
            self.assertEqual(rejected.exception.status_code, 503)
            self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
        finally:
            release.set()
            item = await first
        await self.settled(item.job_id)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.service.active_ids, frozenset())

    async def test_full_tracking_allows_existing_replay_without_creating_an_extra_claim(self):
        self.store.max_entries = 2
        completed = await self.create(KEY)
        await self.settled(completed.job_id)
        self.late_cancel_with_metadata_outage(completed.job_id)
        release, blocker = await self.block_worker()
        try:
            queued = await self.queued(NEXT_KEY)
            await self.cancel_with_metadata_outage(queued.job_id)
            self.assertEqual(self.service.tracked_count, 2)
            # Model independent metadata expiry/removal before a repair pass.
            # The tracking bound must still prevent an extra new claim.
            self.store.discard_queued(queued.job_id, OWNER)
            self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            replay = await self.create(KEY)
            self.assertEqual(replay.job_id, completed.job_id)
            self.assertEqual(replay.state, "completed")
            with self.assertRaises(HTTPException) as rejected:
                await self.create("new_reconciliation_key_0003")
            self.assertEqual(rejected.exception.status_code, 503)
            self.assertEqual(self.service.tracked_count, 2)
            self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual(self.service.reconcile(), 2)
            self.assertEqual(self.service.tracked_count, 0)
        finally:
            release.set()
            await blocker.wait()

    async def test_rejected_admission_is_not_replayed_and_deleted_after_database_recovers(self):
        with patch.object(self.manager, "run", new=AsyncMock(return_value={"ok": True})), \
             patch.object(self.manager, "submit", side_effect=ManagerFull()), \
             patch.object(self.store, "discard_queued", side_effect=sqlite3.OperationalError("temporary failure")):
            with self.assertRaises(HTTPException) as rejected:
                await self.create(KEY)
        self.assertEqual(rejected.exception.status_code, 429)
        self.assertEqual(self.service.pending_count, 1)
        self.assertEqual(self.service.tracked_count, 1)
        self.assertEqual(self.artifacts.reserved_bytes, 0)
        rejected_id = self.store._db.execute("SELECT job_id FROM jobs").fetchone()[0]
        self.assertEqual(self.store._db.execute("SELECT accepted FROM admissions").fetchone()[0], 1)
        with self.assertRaises(HTTPException) as replay:
            await self.create(KEY)
        self.assertEqual(replay.exception.status_code, 503)
        legacy = self.store.create(OWNER)
        self.assertEqual(self.service.reconcile(), 1)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.store.get(legacy.job_id, OWNER).state, "queued")
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM admissions").fetchone()[0], 0)
        recovered = await self.create(KEY, data=b"explicit fresh input")
        await self.settled(recovered.job_id)
        self.assertNotEqual(recovered.job_id, rejected_id)
        self.assertEqual(self.store.get(recovered.job_id, OWNER).state, "completed")

    async def test_rejected_retry_never_changes_active_state_and_rotates_for_fairness(self):
        changed = self.store.create(OWNER)
        self.store.transition(changed.job_id, OWNER, "processing")
        other = self.store.create(OWNER)
        self.service._tracked.update((changed.job_id, other.job_id))
        self.service._pending_discard[changed.job_id] = OWNER
        self.service._pending_discard[other.job_id] = OWNER
        self.assertEqual(self.service.reconcile(max_updates=1), 0)
        self.assertEqual(self.service.reconcile(max_updates=1), 1)
        self.assertEqual(self.store.get(changed.job_id, OWNER).state, "processing")
        self.assertEqual(self.service.pending_count, 1)
        self.assertEqual(self.service.tracked_count, 1)

    async def test_shutdown_makes_one_bounded_terminal_repair_before_closing_artifacts(self):
        item = self.pending_terminal(state="cancelled")
        await self.manager.close()
        self.service.close()
        self.assertEqual(self.store.get(item.job_id, OWNER).state, "cancelled")
        self.assertEqual(self.service.pending_count, 0)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertFalse(self.artifacts.path.exists())

    async def test_lookup_only_idempotency_flag_never_inserts_new_claim(self):
        key = hashlib.sha256(KEY.encode()).hexdigest()
        fingerprint = "a" * 64
        with self.assertRaises(JobCapacityExceeded):
            self.store.create_idempotent(OWNER, key, fingerprint, allow_create=False)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        item, fresh = self.store.create_idempotent(OWNER, key, fingerprint)
        self.assertTrue(fresh)
        self.store.accept_admission(item.job_id, OWNER, key)
        replay, fresh = self.store.create_idempotent(OWNER, key, fingerprint, allow_create=False)
        self.assertFalse(fresh)
        self.assertEqual(replay.job_id, item.job_id)

    async def _stalled_upload(self):
        entered = asyncio.Event()
        cleanup_entered = asyncio.Event()
        finish_cleanup = asyncio.Event()
        class StalledUpload(UploadFile):
            cancellations = 0
            async def read(self, size=-1):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancellations += 1
                    raise
                finally:
                    cleanup_entered.set()
                    await finish_cleanup.wait()
        upload = StalledUpload(file=BytesIO(b"input"), filename="input.txt")
        return upload, entered, cleanup_entered, finish_cleanup

    async def test_shutdown_waits_for_upload_writer_cleanup_before_artifact_close(self):
        upload, entered, cleanup_entered, finish_cleanup = await self._stalled_upload()
        request = asyncio.create_task(self.service.create(upload, "txt:info", ".txt", "", OWNER))
        await asyncio.wait_for(entered.wait(), 3)
        self.assertEqual(self.service.request_count, 1)
        self.assertEqual(self.service.tracked_count, 1)
        job_id = self.store._db.execute("SELECT job_id FROM jobs").fetchone()[0]
        artifact = self.artifacts._entries[job_id]
        first_stop = asyncio.create_task(self.service.stop_preparing())
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        second_stop = asyncio.create_task(self.service.stop_preparing())
        await asyncio.sleep(0)
        self.assertFalse(first_stop.done())
        self.assertFalse(second_stop.done())
        self.assertTrue(artifact.path.exists())
        with self.assertRaisesRegex(RuntimeError, "upload requests still active"):
            self.service.close()
        self.assertTrue(artifact.path.exists())
        finish_cleanup.set()
        await asyncio.wait_for(asyncio.gather(first_stop, second_stop), 3)
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertEqual(upload.cancellations, 1)
        self.assertTrue(upload.file.closed)
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        self.assertFalse(artifact.path.exists())
        await self.service.stop_preparing()

    async def test_shutdown_stops_fingerprinting_before_any_sqlite_claim(self):
        upload, entered, cleanup_entered, finish_cleanup = await self._stalled_upload()
        request = asyncio.create_task(self.service.create(upload, "txt:info", ".txt", "", OWNER, idempotency_key=KEY))
        await asyncio.wait_for(entered.wait(), 3)
        self.assertEqual(self.service.request_count, 1)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        stopping = asyncio.create_task(self.service.stop_preparing())
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        finish_cleanup.set()
        await asyncio.wait_for(stopping, 3)
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        self.assertEqual(self.artifacts.reserved_bytes, 0)

    async def test_shutdown_waits_for_validation_worker_cleanup_before_deleting_input(self):
        entered = asyncio.Event()
        cleanup_entered = asyncio.Event()
        finish_cleanup = asyncio.Event()
        async def worker(payload):
            if payload["operation"] == "validate_only":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup_entered.set()
                    await finish_cleanup.wait()
            self.fail("Shutdown preparation must never start conversion")
        self.service.worker = worker
        request = asyncio.create_task(self.create())
        await asyncio.wait_for(entered.wait(), 3)
        item = next(iter(self.artifacts._entries.values()))
        stopping = asyncio.create_task(self.service.stop_preparing())
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        self.assertFalse(stopping.done())
        self.assertTrue((item.path / "source.txt").exists())
        self.assertEqual(self.manager.active, 1)
        finish_cleanup.set()
        await asyncio.wait_for(stopping, 3)
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertFalse(item.path.exists())
        self.assertEqual(self.manager.active, 0)
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.service.tracked_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    async def test_repeated_shutdown_caller_cancellation_does_not_abandon_upload_cleanup(self):
        upload, entered, cleanup_entered, finish_cleanup = await self._stalled_upload()
        request = asyncio.create_task(self.service.create(upload, "txt:info", ".txt", "", OWNER))
        await asyncio.wait_for(entered.wait(), 3)
        stopping = asyncio.create_task(self.service.stop_preparing())
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        stopping.cancel()
        await asyncio.sleep(0)
        stopping.cancel()
        await asyncio.sleep(0)
        self.assertFalse(stopping.done())
        self.assertEqual(upload.cancellations, 1)
        finish_cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await stopping
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertTrue(upload.file.closed)
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.artifacts.reserved_bytes, 0)
        await self.service.stop_preparing()

    async def test_upload_request_bound_and_late_shutdown_admission_rejection(self):
        self.service.max_requests = 1
        upload, entered, cleanup_entered, finish_cleanup = await self._stalled_upload()
        request = asyncio.create_task(self.service.create(upload, "txt:info", ".txt", "", OWNER, idempotency_key=KEY))
        await asyncio.wait_for(entered.wait(), 3)
        other = UploadFile(file=BytesIO(b"input"), filename="input.txt")
        with self.assertRaises(HTTPException) as overloaded:
            await self.service.create(other, "txt:info", ".txt", "", OWNER, idempotency_key=NEXT_KEY)
        self.assertEqual(overloaded.exception.status_code, 429)
        self.assertTrue(other.file.closed)
        self.assertEqual(self.service.request_count, 1)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        stopping = asyncio.create_task(self.service.stop_preparing())
        await asyncio.wait_for(cleanup_entered.wait(), 3)
        finish_cleanup.set()
        await asyncio.wait_for(stopping, 3)
        with self.assertRaises(asyncio.CancelledError):
            await request
        late = UploadFile(file=BytesIO(b"input"), filename="input.txt")
        with self.assertRaises(HTTPException) as rejected:
            await self.service.create(late, "txt:info", ".txt", "", OWNER)
        self.assertEqual(rejected.exception.status_code, 503)
        self.assertTrue(late.file.closed)
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    async def test_request_registry_releases_slot_even_when_upload_close_fails(self):
        class FailingClose(UploadFile):
            async def close(self):
                await super().close()
                raise OSError("temporary upload close failure")
        upload = FailingClose(file=BytesIO(b"input"), filename="input.txt")
        with self.assertRaises(OSError):
            await self.service.create(upload, "txt:info", ".txt", "", OWNER)
        self.assertTrue(upload.file.closed)
        self.assertEqual(self.service.request_count, 0)
        job_id = self.store._db.execute("SELECT job_id FROM jobs").fetchone()[0]
        await self.settled(job_id)

    async def test_preparation_cannot_deadlock_by_stopping_its_own_request_task(self):
        service = self.service
        class SelfStoppingUpload(UploadFile):
            async def read(self, size=-1):
                await service.stop_preparing()
        upload = SelfStoppingUpload(file=BytesIO(b"input"), filename="input.txt")
        with self.assertRaisesRegex(RuntimeError, "active upload request"):
            await self.service.create(upload, "txt:info", ".txt", "", OWNER)
        self.assertEqual(self.service.request_count, 0)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
        self.assertEqual(self.artifacts.reserved_bytes, 0)
        self.assertTrue(upload.file.closed)
        await self.service.stop_preparing()
