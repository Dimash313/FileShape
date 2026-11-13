"""Owner-only cancellation, explicit re-upload retry and admission idempotency."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import server
from api.worker_runner import WorkerFailed
from test_api import TOKEN, signed_init_data

KEY = "valid_request_key_0001"
NEXT_KEY = "valid_request_key_0002"


class JobControlsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {
            "BOT_TOKEN": TOKEN, "FILESHAPE_STATE_DIR": str(Path(directory.name) / "state"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        limiter = patch.object(server, "RATE_LIMIT_PER_MINUTE", 1000)
        limiter.start()
        self.addCleanup(limiter.stop)
        server.recent_requests.clear()
        self.auth = {"X-Telegram-Init-Data": signed_init_data(user_id=12345)}
        self.other = {"X-Telegram-Init-Data": signed_init_data(user_id=99)}

    def create(self, client, *, key=None, data=b"hello", action="txt:docx", owner=None, path="/api/v1/jobs"):
        headers = dict(self.auth if owner is None else owner)
        if key is not None:
            headers["Idempotency-Key"] = key
        return client.post(path, headers=headers,
                           files={"upload": ("input.txt", data, "text/plain")}, data={"action": action})

    def terminal(self, client, job_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(response.status_code, 200, response.text)
            if response.json()["state"] in {"completed", "failed", "cancelled"}:
                return response.json()
            time.sleep(0.01)
        self.fail("Background job did not reach a terminal state")

    def test_running_cancel_is_owned_and_releases_files_before_response(self):
        real_worker = server.run_worker
        async def events():
            return asyncio.Event(), asyncio.Event()
        with TestClient(server.api) as client:
            entered, cleaned = client.portal.call(events)
            async def worker(payload):
                if payload["operation"] == "single":
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cleaned.set()
                return await real_worker(payload)
            with patch.object(server, "run_worker", side_effect=worker):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                async def started():
                    await asyncio.wait_for(entered.wait(), 3)
                client.portal.call(started)
                artifact = server.background_jobs.artifacts._entries[job_id]
                self.assertEqual(client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.other).status_code, 404)
                self.assertEqual(client.post(f"/api/v1/jobs/{job_id}/cancel").status_code, 401)
                self.assertEqual(server.jobs.get(job_id, 12345).state, "processing")
                response = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.auth)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["state"], "cancelled")
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertTrue(cleaned.is_set())
                self.assertFalse(artifact.path.exists())
                self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)
                repeated = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.auth)
                self.assertEqual(repeated.json(), response.json())
                self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_queued_cancel_never_executes_and_releases_reservation(self):
        with TestClient(server.api) as client:
            manager = server.job_manager
            async def block():
                release = asyncio.Event()
                handles = [manager.submit(release.wait) for _ in range(manager.capacity)]
                async with asyncio.timeout(3):
                    while manager.active != manager.capacity:
                        await asyncio.sleep(0.001)
                return release, handles
            release, blockers = client.portal.call(block)
            async def validation(_operation):
                return {"ok": True}
            try:
                with patch.object(manager, "run", new=validation):
                    accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                self.assertEqual(server.jobs.get(job_id, 12345).state, "queued")
                response = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.auth)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["state"], "cancelled")
                self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)
            finally:
                client.portal.call(release.set)
                async def finish():
                    await asyncio.gather(*(handle.wait() for handle in blockers))
                client.portal.call(finish)

    def test_queued_cancel_metadata_failure_still_removes_unfinished_input(self):
        with TestClient(server.api) as client:
            service = server.background_jobs
            manager = server.job_manager
            async def block():
                release = asyncio.Event()
                handles = [manager.submit(release.wait) for _ in range(manager.capacity)]
                async with asyncio.timeout(3):
                    while manager.active != manager.capacity:
                        await asyncio.sleep(0.001)
                return release, handles
            release, blockers = client.portal.call(block)
            async def validation(_operation):
                return {"ok": True}
            try:
                with patch.object(manager, "run", new=validation):
                    accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                artifact = service.artifacts._entries[job_id]
                original_get = server.jobs.get
                calls = 0
                def metadata_fails_after_owner_check(*args):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return original_get(*args)
                    raise sqlite3.OperationalError("temporary metadata failure")
                with patch.object(server.jobs, "get", side_effect=metadata_fails_after_owner_check):
                    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.auth)
                self.assertEqual(cancelled.status_code, 503)
                self.assertFalse(artifact.path.exists())
                self.assertEqual(service.artifacts.reserved_bytes, 0)
                self.assertNotIn(job_id, service.handles)
            finally:
                client.portal.call(release.set)
                async def finish():
                    await asyncio.gather(*(handle.wait() for handle in blockers))
                client.portal.call(finish)

    def test_late_cancel_metadata_failure_preserves_result_until_finite_ttl(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.terminal(client, job_id)["state"], "completed")
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).content
            async def late_notification():
                future = asyncio.get_running_loop().create_future()
                future.cancel()
                handle = SimpleNamespace(result=future, done=True)
                service = server.background_jobs
                service.handles[job_id] = handle
                service.owners[job_id] = 12345
                with patch.object(service.store, "get", side_effect=sqlite3.OperationalError("temporary metadata failure")):
                    service._settled(job_id, 12345, handle)
            client.portal.call(late_notification)
            self.assertEqual(server.jobs.get(job_id, 12345).state, "completed")
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).content, result)
            self.assertIsNotNone(server.background_jobs.artifacts._entries[job_id].expires_at)

    def test_completed_cancel_and_late_cancel_notification_preserve_result(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            before = self.terminal(client, job_id)
            self.assertEqual(before["state"], "completed")
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).content
            cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=self.auth)
            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(cancelled.json(), before)
            async def late_notification():
                # Model completion committing before a cancellation result is
                # delivered by the manager to the settlement callback.
                future = asyncio.get_running_loop().create_future()
                future.cancel()
                handle = SimpleNamespace(result=future, done=True)
                service = server.background_jobs
                service.handles[job_id] = handle
                service.owners[job_id] = 12345
                service._settled(job_id, 12345, handle)
            client.portal.call(late_notification)
            self.assertEqual(server.jobs.get(job_id, 12345).state, "completed")
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).content, result)

    def test_missing_active_handle_is_not_falsely_cancelled(self):
        with TestClient(server.api) as client:
            item = server.jobs.create(12345)
            response = client.post(f"/api/v1/jobs/{item.job_id}/cancel", headers=self.auth)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(server.jobs.get(item.job_id, 12345).state, "queued")
            self.assertEqual(client.post(f"/api/v1/jobs/{item.job_id}/cancel", headers=self.other).status_code, 404)

    def test_keyed_replay_bypasses_quota_and_conflicting_bytes_or_action_rejected(self):
        with TestClient(server.api) as client:
            first = self.create(client, key=KEY)
            self.assertEqual(first.status_code, 202, first.text)
            job_id = first.json()["job_id"]
            self.assertEqual(self.terminal(client, job_id)["state"], "completed")
            server.background_jobs.artifacts.max_bytes = 1
            replay = self.create(client, key=KEY)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()["job_id"], job_id)
            self.assertEqual(replay.json()["state"], "completed")
            self.assertEqual(self.create(client, key=KEY, data=b"changed").status_code, 409)
            self.assertEqual(self.create(client, key=KEY, action="txt:info").status_code, 409)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_failed_admission_releases_claim_for_valid_resubmission(self):
        with TestClient(server.api) as client:
            artifacts = server.background_jobs.artifacts
            artifacts.max_bytes = 1
            rejected = self.create(client, key=KEY)
            self.assertEqual(rejected.status_code, 503, rejected.text)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            artifacts.max_bytes = 256 * 1024**2
            accepted = self.create(client, key=KEY, data=b"new contents")
            self.assertEqual(accepted.status_code, 202, accepted.text)
            self.assertEqual(self.terminal(client, accepted.json()["job_id"])["state"], "completed")

    def test_pending_duplicate_waits_for_first_admission_without_second_worker(self):
        real_worker = server.run_worker
        async def events():
            return asyncio.Event(), asyncio.Event()
        with TestClient(server.api) as client:
            entered, release = client.portal.call(events)
            calls = []
            async def worker(payload):
                if payload["operation"] == "validate_only":
                    calls.append(True)
                    entered.set()
                    await release.wait()
                return await real_worker(payload)
            with patch.object(server, "run_worker", side_effect=worker), ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.create, client, key=KEY)
                try:
                    async def started():
                        await asyncio.wait_for(entered.wait(), 3)
                    client.portal.call(started)
                    duplicate = self.create(client, key=KEY)
                    self.assertEqual(duplicate.status_code, 409, duplicate.text)
                    self.assertEqual(duplicate.headers["retry-after"], "1")
                finally:
                    client.portal.call(release.set)
                accepted = first.result(timeout=8)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            self.assertEqual(calls, [True])
            self.assertEqual(self.terminal(client, accepted.json()["job_id"])["state"], "completed")

    def test_retry_requires_owner_valid_reupload_and_key_and_is_itself_repeatable(self):
        real_worker = server.run_worker
        async def fail(payload):
            if payload["operation"] == "single":
                raise WorkerFailed("private operation detail")
            return await real_worker(payload)
        with TestClient(server.api) as client:
            with patch.object(server, "run_worker", side_effect=fail):
                first = self.create(client)
                self.assertEqual(first.status_code, 202, first.text)
                original = first.json()["job_id"]
                self.assertEqual(self.terminal(client, original)["state"], "failed")
            path = f"/api/v1/jobs/{original}/retry"
            self.assertEqual(self.create(client, key=KEY, path=path, owner=self.other).status_code, 404)
            self.assertEqual(self.create(client, path=path).status_code, 422)
            self.assertEqual(self.create(client, key=KEY, path=path, data=b"").status_code, 422)
            with patch.object(server, "run_worker", side_effect=fail):
                retried = self.create(client, key=KEY, path=path)
                self.assertEqual(retried.status_code, 202, retried.text)
                retry_id = retried.json()["job_id"]
                self.assertNotEqual(retry_id, original)
                self.assertEqual(self.terminal(client, retry_id)["state"], "failed")
            replay = self.create(client, key=KEY, path=path)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()["job_id"], retry_id)
            self.assertEqual(replay.json()["state"], "failed")
            next_retry = self.create(client, key=NEXT_KEY, path=f"/api/v1/jobs/{retry_id}/retry")
            self.assertEqual(next_retry.status_code, 202, next_retry.text)
            next_id = next_retry.json()["job_id"]
            self.assertEqual(self.terminal(client, next_id)["state"], "completed")
            self.assertEqual(server.jobs.get(original, 12345).state, "failed")
            self.assertEqual(server.jobs.get(retry_id, 12345).state, "failed")
            self.assertEqual(self.create(client, key=NEXT_KEY, path=path).status_code, 409)

    def test_completed_or_active_retry_rejected_and_retry_ingress_capped(self):
        with TestClient(server.api) as client:
            queued = server.jobs.create(12345)
            response = self.create(client, key=KEY, path=f"/api/v1/jobs/{queued.job_id}/retry")
            self.assertEqual(response.status_code, 409)
            first = self.create(client)
            self.assertEqual(first.status_code, 202, first.text)
            completed = first.json()["job_id"]
            self.assertEqual(self.terminal(client, completed)["state"], "completed")
            self.assertEqual(self.create(client, key=KEY, path=f"/api/v1/jobs/{completed}/retry").status_code, 409)
            oversized = client.post(f"/api/v1/jobs/{completed}/retry", content=b"x", headers={"content-length": "999999999"})
            self.assertEqual(oversized.status_code, 413)

    def test_invalid_key_is_rejected_without_claim_or_artifact(self):
        with TestClient(server.api) as client:
            for key in ("short", "x" * 129, "has spaces in request key"):
                with self.subTest(key=key):
                    self.assertEqual(self.create(client, key=key).status_code, 422)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)
