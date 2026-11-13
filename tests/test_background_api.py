"""Background acceptance, real conversion, owner isolation and lifecycle regressions."""
import asyncio
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import server
from api.jobs import JobNotFound
from api.worker_runner import WorkerFailed
from test_api import signed_init_data, TOKEN


class BackgroundAPITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state_dir = Path(directory.name) / "state"
        settings = patch.dict(os.environ, {
            "BOT_TOKEN": TOKEN,
            "FILESHAPE_STATE_DIR": str(self.state_dir),
        })
        settings.start()
        self.addCleanup(settings.stop)
        limiter = patch.object(server, "RATE_LIMIT_PER_MINUTE", 1000)
        limiter.start()
        self.addCleanup(limiter.stop)
        server.recent_requests.clear()
        self.auth = {"X-Telegram-Init-Data": signed_init_data(user_id=12345)}
        self.other_auth = {"X-Telegram-Init-Data": signed_init_data(user_id=99)}

    def create(self, client, filename="input.txt", data=b"hello", action="txt:docx", **kwargs):
        return client.post(
            "/api/v1/jobs", headers=self.auth,
            files={"upload": (filename, data, "application/octet-stream")},
            data={"action": action, **kwargs},
        )

    def wait_terminal(self, client, job_id):
        deadline = time.monotonic() + 8
        last = None
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(response.status_code, 200, response.text)
            last = response.json()
            if last["state"] in {"completed", "failed", "cancelled"}:
                return last
            time.sleep(0.03)
        self.fail(f"Background job did not finish: {last}")

    def test_real_conversion_returns_202_and_owner_only_result(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            body = accepted.json()
            self.assertRegex(body["job_id"], r"^[A-Za-z0-9_-]{32}$")
            self.assertEqual(set(body), {"job_id", "state", "created_at", "updated_at"})
            self.assertIn(body["state"], {"queued", "processing", "completed"})
            self.assertEqual(accepted.headers["cache-control"], "no-store")
            job_id = body["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            usage = client.get("/api/v1/usage", headers=self.auth)
            self.assertEqual(usage.status_code, 200)
            self.assertTrue(usage.json()["enforced"])
            self.assertEqual(usage.json()["daily_used"], 1)
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.content.startswith(b"PK"))
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual(result.headers["x-content-type-options"], "nosniff")
            self.assertIn("attachment", result.headers["content-disposition"])
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.other_auth).status_code, 404)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}", headers=self.other_auth).status_code, 404)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result").status_code, 401)
            # Authorized downloads remain repeatable during the result TTL.
            repeated = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(repeated.content, result.content)

    def test_inspection_result_is_valid_json(self):
        with TestClient(server.api) as client:
            accepted = self.create(client, data=b"first\nsecond", action="txt:info")
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn("application/json", result.headers["content-type"])
            self.assertEqual(result.json()["info"]["lines"], 2)

    def test_background_api_fails_closed_without_lifespan(self):
        with patch.object(server, "background_jobs", None):
            client = TestClient(server.api)
            self.addCleanup(client.close)
            response = self.create(client)
            self.assertEqual(response.status_code, 503, response.text)

    def test_create_requires_signed_authentication(self):
        with TestClient(server.api) as client:
            response = client.post("/api/v1/jobs", files={"upload": ("input.txt", b"hello")}, data={"action": "txt:docx"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_invalid_uploads_are_rejected_before_acceptance(self):
        with TestClient(server.api) as client:
            for name, data, action, pages in (
                ("empty.txt", b"", "txt:docx", ""),
                ("spoof.pdf", b"not a pdf", "pdf:rotate", ""),
                ("input.txt", b"hello", "pdf:rotate", ""),
                ("input.txt", b"hello", "txt:docx", "1" * 91),
            ):
                with self.subTest(name=name, action=action, pages=len(pages)):
                    response = self.create(client, filename=name, data=data, action=action, pages=pages)
                    self.assertEqual(response.status_code, 422, response.text)
            active = server.jobs._db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','processing')").fetchone()[0]
            self.assertEqual(active, 0)

    def test_actual_streamed_upload_size_is_limited(self):
        with TestClient(server.api) as client:
            with patch.object(server, "MAX_INPUT_BYTES", 8):
                response = self.create(client, data=b"x" * 9)
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','processing')").fetchone()[0], 0)

    def test_background_route_enforces_ingress_before_multipart_parsing(self):
        with TestClient(server.api) as client:
            response = client.post(
                "/api/v1/jobs", content=b"x",
                headers={"content-length": "999999999", "content-type": "application/octet-stream"},
            )
            self.assertEqual(response.status_code, 413)

    def test_client_filename_does_not_control_server_paths_or_download_name(self):
        with TestClient(server.api) as client:
            accepted = self.create(client, filename="../../private/input.txt")
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(result.status_code, 200, result.text)
            disposition = result.headers["content-disposition"]
            self.assertNotIn("private", disposition)
            self.assertNotIn("..", disposition)
            self.assertTrue(result.content.startswith(b"PK"))

    def test_worker_failure_is_terminal_and_has_no_download(self):
        real_worker = server.run_worker
        async def fail_conversion(payload, *args, **kwargs):
            if payload["operation"] == "single":
                raise WorkerFailed("sensitive worker details")
            return await real_worker(payload, *args, **kwargs)
        with TestClient(server.api) as client:
            with patch.object(server, "run_worker", side_effect=fail_conversion):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                status = self.wait_terminal(client, job_id)
            self.assertEqual(status["state"], "failed")
            self.assertNotIn("sensitive", str(status))
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(result.status_code, 404)
            self.assertNotIn("sensitive", result.text)

    def test_worker_result_path_cannot_escape_artifact_directory(self):
        real_worker = server.run_worker
        async def unsafe_result(payload, *args, **kwargs):
            if payload["operation"] == "single":
                return {"ok": True, "filename": "../../instance.lock", "bytes": 4}
            return await real_worker(payload, *args, **kwargs)
        with TestClient(server.api) as client:
            with patch.object(server, "run_worker", side_effect=unsafe_result):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "failed")
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_running_job_is_accepted_before_finish_and_result_is_unavailable(self):
        real_worker = server.run_worker
        entered = None
        release = None
        async def initialize():
            nonlocal entered, release
            entered = asyncio.Event()
            release = asyncio.Event()
        async def slow_conversion(payload, *args, **kwargs):
            if payload["operation"] == "single":
                entered.set()
                await release.wait()
            return await real_worker(payload, *args, **kwargs)
        with TestClient(server.api) as client:
            client.portal.call(initialize)
            with patch.object(server, "run_worker", side_effect=slow_conversion):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                try:
                    async def wait_entered():
                        await asyncio.wait_for(entered.wait(), 3)
                    client.portal.call(wait_entered)
                    status = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
                    self.assertEqual(status.json()["state"], "processing")
                    self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 409)
                finally:
                    client.portal.call(release.set)
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")

    def test_restart_keeps_metadata_without_claiming_result_recovery(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
        with TestClient(server.api) as client:
            status = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["state"], "completed")
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_shutdown_cancels_active_job_and_releases_its_files(self):
        work_paths = []
        real_worker = server.run_worker
        entered = None
        async def initialize():
            nonlocal entered
            entered = asyncio.Event()
        async def never_finish(payload, *args, **kwargs):
            if payload["operation"] == "single":
                work_paths.append(Path(payload["work"]))
                entered.set()
                await asyncio.Event().wait()
            return await real_worker(payload, *args, **kwargs)
        with patch.object(server, "run_worker", side_effect=never_finish):
            with TestClient(server.api) as client:
                client.portal.call(initialize)
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                async def wait_entered():
                    await asyncio.wait_for(entered.wait(), 3)
                client.portal.call(wait_entered)
                # Shutdown must cancel bounded work rather than wait forever.
        self.assertTrue(work_paths)
        self.assertTrue(all(not path.exists() for path in work_paths))
        with TestClient(server.api) as client:
            status = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["state"], "cancelled")
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_expired_result_is_removed_and_owner_cannot_download_it(self):
        with TestClient(server.api) as client:
            artifacts = server.background_jobs.artifacts
            artifacts.ttl = 0.02
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            time.sleep(0.03)
            client.portal.call(artifacts.prune)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_artifact_quota_rejects_before_job_acceptance(self):
        with TestClient(server.api) as client:
            server.background_jobs.artifacts.max_bytes = 1
            response = self.create(client)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','processing')").fetchone()[0], 0)

    def test_preacceptance_rejection_does_not_exhaust_metadata_capacity(self):
        with TestClient(server.api) as client:
            server.jobs.max_entries = 1
            artifacts = server.background_jobs.artifacts
            artifacts.max_bytes = 1
            rejected = self.create(client)
            self.assertEqual(rejected.status_code, 503, rejected.text)
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            artifacts.max_bytes = 256 * 1024 * 1024
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_rejected_admission_cleanup_cannot_delete_foreign_or_running_records(self):
        with TestClient(server.api):
            store = server.jobs
            own = store.create(12345)
            self.assertFalse(store.discard_queued(own.job_id, 99))
            self.assertEqual(store.get(own.job_id, 12345).state, "queued")
            store.transition(own.job_id, 12345, "processing")
            self.assertFalse(store.discard_queued(own.job_id, 12345))
            self.assertEqual(store.get(own.job_id, 12345).state, "processing")
            queued = store.create(12345)
            self.assertTrue(store.discard_queued(queued.job_id, 12345))
            self.assertFalse(store.discard_queued(queued.job_id, 12345))
            with self.assertRaises(JobNotFound):
                store.get(queued.job_id, 12345)

    def test_full_dispatch_queue_rejects_instead_of_creating_unbounded_tasks(self):
        with TestClient(server.api) as client:
            async def fill_dispatch():
                release = asyncio.Event()
                manager = server.job_manager
                active = [manager.submit(release.wait) for _ in range(manager.capacity)]
                async with asyncio.timeout(3):
                    while manager.active != manager.capacity:
                        await asyncio.sleep(0.001)
                pending = []
                for _ in range(20):
                    pending.append(manager.submit(release.wait))
                return release, active + pending
            release, handles = client.portal.call(fill_dispatch)
            try:
                response = self.create(client)
                self.assertEqual(response.status_code, 429, response.text)
                self.assertEqual(server.jobs._db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','processing')").fetchone()[0], 0)
            finally:
                client.portal.call(release.set)
                async def finish_all():
                    async with asyncio.timeout(3):
                        await asyncio.gather(*(handle.wait() for handle in handles))
                client.portal.call(finish_all)

    def test_queued_handle_cancellation_discards_upload_and_reservation(self):
        with TestClient(server.api) as client:
            service = server.background_jobs
            manager = server.job_manager
            async def fill_workers():
                release = asyncio.Event()
                blockers = [manager.submit(release.wait) for _ in range(manager.capacity)]
                async with asyncio.timeout(3):
                    while manager.active != manager.capacity:
                        await asyncio.sleep(0.001)
                return release, blockers
            release, blockers = client.portal.call(fill_workers)
            async def validated(_operation):
                return {"ok": True}
            try:
                # Isolate queued-job lifecycle from the validation subprocess,
                # which intentionally cannot run while all workers are occupied.
                with patch.object(manager, "run", new=validated):
                    accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                self.assertEqual(client.get(f"/api/v1/jobs/{job_id}", headers=self.auth).json()["state"], "queued")
                self.assertGreater(service.artifacts.reserved_bytes, 0)
                work_path = service.artifacts._entries[job_id].path
                client.portal.call(service.handles[job_id].cancel)
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "cancelled")
                self.assertFalse(work_path.exists())
                self.assertEqual(service.artifacts.reserved_bytes, 0)
                self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)
            finally:
                client.portal.call(release.set)
                async def finish_blockers():
                    async with asyncio.timeout(3):
                        await asyncio.gather(*(handle.wait() for handle in blockers))
                client.portal.call(finish_blockers)

    def test_running_handle_cancellation_releases_result_quota(self):
        real_worker = server.run_worker
        entered = None
        async def initialize():
            nonlocal entered
            entered = asyncio.Event()
        async def never_finish(payload, *args, **kwargs):
            if payload["operation"] == "single":
                entered.set()
                await asyncio.Event().wait()
            return await real_worker(payload, *args, **kwargs)
        with TestClient(server.api) as client:
            client.portal.call(initialize)
            with patch.object(server, "run_worker", side_effect=never_finish):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                async def wait_entered():
                    await asyncio.wait_for(entered.wait(), 3)
                client.portal.call(wait_entered)
                client.portal.call(server.background_jobs.handles[job_id].cancel)
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "cancelled")
                self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)

    def test_processing_deadline_fails_job_and_releases_quota(self):
        async def timed_worker(payload):
            if payload["operation"] == "validate_only":
                return {"ok": True}
            await asyncio.Event().wait()
        with TestClient(server.api) as client:
            server.job_manager.timeout = 0.03
            with patch.object(server, "run_worker", side_effect=timed_worker):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "failed")
                self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)

    def test_output_size_limit_fails_job_without_retaining_result(self):
        with TestClient(server.api) as client:
            with patch.object(server, "MAX_RESULT_BYTES", 1), patch.object(server.background_jobs, "max_result", 1):
                accepted = self.create(client)
                self.assertEqual(accepted.status_code, 202, accepted.text)
                job_id = accepted.json()["job_id"]
                self.assertEqual(self.wait_terminal(client, job_id)["state"], "failed")
            self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 404)

    def test_download_concurrency_limit_rejects_before_opening_result(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            with patch.object(server, "download_slots", asyncio.Semaphore(0)):
                response = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth).status_code, 200)

    def test_symlink_result_is_unavailable_without_disclosing_target(self):
        with TestClient(server.api) as client:
            accepted = self.create(client)
            self.assertEqual(accepted.status_code, 202, accepted.text)
            job_id = accepted.json()["job_id"]
            self.assertEqual(self.wait_terminal(client, job_id)["state"], "completed")
            item = server.background_jobs.artifacts._entries[job_id]
            target = self.state_dir / "private.txt"
            target.write_bytes(b"secret-not-a-result")
            result_path = item.path / item.filename
            result_path.unlink()
            result_path.symlink_to(target)
            response = client.get(f"/api/v1/jobs/{job_id}/result", headers=self.auth)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("secret-not-a-result", response.text)
            self.assertEqual(target.read_bytes(), b"secret-not-a-result")

    def test_missing_and_traversal_identifiers_cannot_retrieve_files(self):
        with TestClient(server.api) as client:
            for path in (
                "/api/v1/jobs/" + "A" * 32 + "/result",
                "/api/v1/jobs/..%2F..%2Fetc%2Fpasswd/result",
                "/api/v1/jobs/instance.lock/result",
            ):
                with self.subTest(path=path):
                    response = client.get(path, headers=self.auth)
                    self.assertEqual(response.status_code, 404, response.text)
