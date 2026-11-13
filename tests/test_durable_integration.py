"""Real SQLite/API lifecycle, ownership and competing-process regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from api import server
from api.admission import AdmissionQueue
from api.durable_jobs import DurableJobStore
from api.job_runtime import JobRuntime
from api.jobs import JobCapacityExceeded, JobNotFound
from test_api import signed_init_data, TOKEN


class DurableIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "state"
        env = patch.dict(os.environ, {"BOT_TOKEN": TOKEN, "FILESHAPE_STATE_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.auth = {"X-Telegram-Init-Data": signed_init_data(user_id=12345)}
        server.recent_requests.clear()

    def test_real_conversion_persists_across_restart_with_owner_isolation(self):
        with TestClient(server.api) as client:
            response = client.post("/api/v1/convert", headers=self.auth,
                                   files={"upload": ("input.txt", b"hello", "text/plain")},
                                   data={"action": "txt:docx"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.content.startswith(b"PK"))
            job_id = response.headers["X-FileShape-Job-Id"]
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}", headers=self.auth).json()["state"], "completed")
            usage = client.get("/api/v1/usage", headers=self.auth).json()
            self.assertTrue(usage["enforced"])
            self.assertEqual(usage["daily_used"], 1)
        with TestClient(server.api) as client:
            response = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["state"], "completed")
            other = {"X-Telegram-Init-Data": signed_init_data(user_id=99)}
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}", headers=other).status_code, 404)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}").status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_lifespan_disabled_fails_closed(self):
        with patch.object(server, "jobs", None), patch.object(server, "job_runtime", None):
            with TestClient(server.api) as started:
                self.assertEqual(started.get("/ready").status_code, 200)
            client = TestClient(server.api)
            self.addCleanup(client.close)
            response = client.post("/api/v1/convert", headers=self.auth,
                                   files={"upload": ("input.txt", b"hello", "text/plain")},
                                   data={"action": "txt:docx"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(client.get("/api/v1/jobs/unknown", headers=self.auth).status_code, 503)
            self.assertEqual(client.get("/ready").status_code, 503)

    def test_second_process_cannot_fail_active_jobs(self):
        runtime = JobRuntime(self.root)
        self.addCleanup(runtime.close)
        job = runtime.store.create(12345)
        runtime.store.transition(job.job_id, 12345, "processing")
        code = "from api.job_runtime import JobRuntime; import sys; JobRuntime(sys.argv[1])"
        child = subprocess.run([sys.executable, "-c", code, str(self.root)], capture_output=True, timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn(b"Another API process", child.stderr)
        self.assertEqual(runtime.store.get(job.job_id, 12345).state, "processing")
        runtime.close()
        with TestClient(server.api) as client:
            self.assertEqual(client.get(f"/api/v1/jobs/{job.job_id}", headers=self.auth).json()["state"], "failed")

    def test_capacity_check_is_atomic_between_connections(self):
        path = Path(self.tmp.name) / "bounded.sqlite3"
        with DurableJobStore(path, max_entries=1) as first, DurableJobStore(path, max_entries=1) as second:
            barrier = threading.Barrier(2)
            def create(store):
                barrier.wait(timeout=5)
                try:
                    return store.create(11).state
                except JobCapacityExceeded:
                    return "full"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(create, (first, second)))
            self.assertCountEqual(results, ["queued", "full"])
            self.assertEqual(first._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_expiry_is_deterministic_and_does_not_remove_active(self):
        with DurableJobStore(Path(self.tmp.name) / "ttl.sqlite3", max_entries=2, retention_seconds=60) as store:
            with patch("api.durable_jobs.time.time", return_value=1000):
                active = store.create(11)
                done = store.create(11)
                store.transition(done.job_id, 11, "failed")
            with patch("api.durable_jobs.time.time", return_value=1060):
                replacement = store.create(11)
                self.assertEqual(store.get(active.job_id, 11).state, "queued")
                self.assertEqual(store.get(replacement.job_id, 11).state, "queued")
                with self.assertRaises(JobNotFound):
                    store.get(done.job_id, 11)

    def test_workspace_failure_releases_capacity_and_fails_job(self):
        with TestClient(server.api) as client:
            with patch("api.server.Workspace", side_effect=OSError("disk full")):
                response = client.post("/api/v1/convert", headers=self.auth,
                                       files={"upload": ("input.txt", b"hello", "text/plain")},
                                       data={"action": "txt:docx"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(server.slots._value, server.MAX_CONCURRENT_JOBS)
            self.assertEqual(server.jobs._db.execute("SELECT state FROM jobs").fetchone()[0], "failed")
            self.assertEqual(server.jobs.usage_snapshot(12345)["daily_used"], 0)

    def test_unsafe_directory_rejected(self):
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        with self.assertRaises(RuntimeError):
            JobRuntime(self.root)


class DurableWaitingCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_request_cancel_closes_upload_and_persists_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            with DurableJobStore(Path(directory) / "jobs.sqlite3") as store:
                upload = UploadFile(file=BytesIO(b"hello"), filename="input.txt")
                queue = AdmissionQueue()
                with patch.object(server, "jobs", store), patch.object(server, "slots", asyncio.Semaphore(0)), patch.object(server, "admission", queue):
                    task = asyncio.create_task(server.convert(upload=upload, action="txt:docx", pages="", user_id=11))
                    try:
                        for _ in range(100):
                            if queue.waiting:
                                break
                            await asyncio.sleep(0.001)
                        self.assertEqual(queue.waiting, 1)
                    finally:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    self.assertTrue(upload.file.closed)
                    self.assertEqual(queue.waiting, 0)
                    self.assertEqual(store._db.execute("SELECT state FROM jobs").fetchone()[0], "cancelled")

    async def test_database_transition_failure_still_releases_slot_and_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            with DurableJobStore(Path(directory) / "jobs.sqlite3") as store:
                upload = UploadFile(file=BytesIO(b"hello"), filename="input.txt")
                semaphore = asyncio.Semaphore(1)
                with patch.object(server, "jobs", store), patch.object(server, "slots", semaphore), patch.object(server, "admission", AdmissionQueue()):
                    with patch.object(store, "transition", side_effect=sqlite3.OperationalError("private details")):
                        with self.assertRaises(HTTPException) as error:
                            await server.convert(upload=upload, action="txt:docx", pages="", user_id=11)
                    self.assertEqual(error.exception.status_code, 503)
                    self.assertNotIn("private details", str(error.exception.detail))
                    self.assertEqual(semaphore._value, 1)
                    self.assertTrue(upload.file.closed)

    async def test_running_cancellation_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            with DurableJobStore(Path(directory) / "jobs.sqlite3") as store:
                upload = UploadFile(file=BytesIO(b"hello"), filename="input.txt")
                entered = asyncio.Event()
                async def worker(payload):
                    entered.set()
                    await asyncio.Event().wait()
                semaphore = asyncio.Semaphore(1)
                with patch.object(server, "jobs", store), patch.object(server, "slots", semaphore), patch.object(server, "admission", AdmissionQueue()), patch.object(server, "run_worker", side_effect=worker):
                    task = asyncio.create_task(server.convert(upload=upload, action="txt:docx", pages="", user_id=11))
                    try:
                        await asyncio.wait_for(entered.wait(), 5)
                    finally:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    self.assertEqual(store._db.execute("SELECT state FROM jobs").fetchone()[0], "cancelled")
                    self.assertEqual(semaphore._value, 1)
                    self.assertTrue(upload.file.closed)
