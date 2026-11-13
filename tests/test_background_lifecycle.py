"""Crash retention, startup failure and download cleanup regressions."""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from api import server
from api.admission import AdmissionQueue
from api.artifacts import ArtifactStore
from api.background_jobs import BackgroundJobs
from api.job_manager import JobManager
from api.job_runtime import JobRuntime
from api.workspaces import STALE_SECONDS, OrphanCleaner, cleanup_orphans
from fastapi import UploadFile


class BackgroundLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_cleaner_close_still_releases_sqlite_after_workers_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = JobRuntime(directory)
            cleaner = SimpleNamespace(close=Mock(side_effect=OSError("cleanup descriptor failed")))
            with patch.multiple(server, job_runtime=runtime, jobs=runtime.store, job_manager=None,
                                background_jobs=None, metadata_maintenance=None, orphan_cleaner=cleaner,
                                shutdown_task=None, admission=AdmissionQueue(20, 90)):
                with self.assertRaisesRegex(OSError, "descriptor failed"):
                    await server.stop_accepting_conversions()
                self.assertIsNone(server.job_runtime)
                self.assertIsNone(server.orphan_cleaner)
                self.assertIsNone(server.jobs)
            reopened = JobRuntime(directory)
            reopened.close()

    async def test_cancelled_shutdown_joins_worker_before_releasing_instance_and_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = JobRuntime(root / "state")
            artifacts = ArtifactStore(root / "workspaces")
            manager = JobManager(1)
            started = asyncio.Event()
            cleaning = asyncio.Event()
            release = asyncio.Event()
            async def worker(payload):
                if payload["operation"] == "validate_only":
                    return {"ok": True}
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
            service = BackgroundJobs(runtime.store, manager, artifacts, worker, 1024, 1024)
            item = await service.create(UploadFile(file=BytesIO(b"input"), filename="input.txt"),
                                        "txt:info", ".txt", "", 11)
            await asyncio.wait_for(started.wait(), 3)
            artifact = artifacts._entries[item.job_id]
            with patch.multiple(server, job_runtime=runtime, jobs=runtime.store, job_manager=manager,
                                background_jobs=service, metadata_maintenance=None, orphan_cleaner=None,
                                shutdown_task=None, admission=AdmissionQueue(20, 90)):
                stopping = asyncio.create_task(server.stop_accepting_conversions())
                try:
                    await asyncio.wait_for(cleaning.wait(), 3)
                    stopping.cancel()
                    await asyncio.sleep(0)
                    stopping.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(stopping.done())
                    self.assertTrue(artifact.path.exists())
                    self.assertEqual(runtime.store.get(item.job_id, 11).state, "processing")
                    with self.assertRaisesRegex(RuntimeError, "Another API process"):
                        JobRuntime(root / "state")
                finally:
                    release.set()
                    await asyncio.gather(stopping, return_exceptions=True)
                self.assertTrue(stopping.cancelled())
                self.assertFalse(artifacts.path.exists())
                self.assertIsNone(server.job_runtime)
                self.assertIsNone(server.background_jobs)
                await server.stop_accepting_conversions()
            reopened = JobRuntime(root / "state")
            try:
                self.assertEqual(reopened.store.get(item.job_id, 11).state, "cancelled")
            finally:
                reopened.close()

    async def test_periodic_cleanup_removes_stale_background_generation_but_preserves_locked_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orphan = root / "fileshape_background_crashed"
            orphan.mkdir(mode=0o700)
            (orphan / ".active.lock").touch(mode=0o600)
            (orphan / "old-result.txt").write_bytes(b"expired")
            active = ArtifactStore(root=root)
            try:
                item = active.reserve("A" * 32, 1024)
                source = item.path / "source.txt"
                source.write_bytes(b"active input")
                old = time.time() - STALE_SECONDS - 100
                os.utime(orphan, (old, old))
                os.utime(active.path, (old, old))
                sleep_calls = 0
                async def two_ticks(delay):
                    nonlocal sleep_calls
                    sleep_calls += 1
                    if sleep_calls > 1:
                        raise asyncio.CancelledError()
                store = SimpleNamespace(prune_terminal=Mock())
                # Run one real maintenance tick without waiting a minute. This
                # exercises actual age/lock deletion through the periodic path.
                with patch("api.workspaces.workspace_root", return_value=root), \
                     patch.object(server, "cleanup_orphans", wraps=cleanup_orphans) as sweep, \
                     patch.object(server, "background_jobs", SimpleNamespace(artifacts=active, reconcile=Mock())), \
                     patch.object(server.asyncio, "sleep", side_effect=two_ticks):
                    with self.assertRaises(asyncio.CancelledError):
                        await server.maintain_metadata(store)
                sweep.assert_called_once_with()
                store.prune_terminal.assert_called_once_with()
                self.assertFalse(orphan.exists(), "Expired orphan generation survived periodic cleanup")
                self.assertTrue(active.path.exists(), "A held flock must protect old active generations")
                self.assertEqual(source.read_bytes(), b"active input")
            finally:
                active.close()

    async def test_unsafe_artifact_root_startup_failure_releases_sqlite_instance_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            unsafe = root / "unsafe-artifacts"
            unsafe.mkdir(mode=0o755)
            unsafe.chmod(0o755)  # Do not let the test runner's umask hide the fault.
            with patch.dict(os.environ, {"FILESHAPE_STATE_DIR": str(state)}), \
                 patch.object(server, "job_runtime", None), \
                 patch.object(server, "cleanup_orphans", return_value=0), \
                 patch.object(server, "ArtifactStore", side_effect=lambda: ArtifactStore(root=unsafe)):
                with self.assertRaisesRegex(ValueError, "private and service-owned"):
                    await server.remove_abandoned_workspaces()
            # Reacquiring the same runtime proves both failed startup's SQLite
            # connection and its exclusive instance lock were released.
            reopened = JobRuntime(state)
            try:
                job = reopened.store.create(11)
                self.assertEqual(reopened.store.get(job.job_id, 11).state, "queued")
            finally:
                reopened.close()

    async def test_failed_download_send_and_file_close_still_release_download_permit(self):
        class FailedArtifactClose(BytesIO):
            def close(self):
                super().close()
                # Model a lease that closed its fd but could not remove the
                # deferred artifact directory while releasing its reservation.
                raise OSError("deferred artifact deletion failed")
        file = FailedArtifactClose(b"result")
        permits = asyncio.Semaphore(1)
        await permits.acquire()
        response = server.ResultStream(file, 6, "application/octet-stream", "result.bin")
        async def receive():
            return {"type": "http.disconnect"}
        async def disconnected_send(message):
            raise OSError("client disconnected")
        scope = {"type": "http", "method": "GET", "headers": [],
                 "asgi": {"version": "3.0", "spec_version": "2.4"}}
        with patch.object(server, "download_slots", permits):
            with self.assertRaisesRegex(OSError, "deferred artifact deletion failed"):
                await response(scope, receive, disconnected_send)
        self.assertTrue(file.closed)
        # Verify usable capacity, not just an internal semaphore counter.
        async with asyncio.timeout(1):
            await permits.acquire()
        permits.release()
