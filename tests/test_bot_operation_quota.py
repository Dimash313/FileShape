"""Bot processing leases and signed HTTP quota bridge regression tests."""
import hashlib
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import httpx

from api.durable_jobs import DurableJobStore
from api.internal_access import ReplayGuard, sign_access_request
from api.jobs import JobNotFound, JobStateError
from api.usage_ledger import OperationConcurrencyExceeded
from api import server
from services.bot_operations import (
    BotOperationUnavailable, reserve_bot_operation,
)

OWNER = 23456
TOKEN = "123456:BOT-QUOTA-TEST"


class BotLeaseStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DurableJobStore(Path(self.tmp.name) / "jobs.sqlite3")
        self.addCleanup(self.store.close)

    def digest(self, value):
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def test_exactly_once_success_and_owner_isolation(self):
        job, created = self.store.reserve_bot_operation(OWNER, self.digest("operation-one"))
        self.assertTrue(created)
        self.assertEqual(job.state, "processing")
        replay, created = self.store.reserve_bot_operation(OWNER, self.digest("operation-one"))
        self.assertFalse(created)
        self.assertEqual(replay.job_id, job.job_id)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)
        with self.assertRaises(JobNotFound):
            self.store.settle_bot_operation(OWNER + 1, job.job_id, success=True)
        result = self.store.settle_bot_operation(OWNER, job.job_id, success=True)
        self.assertEqual(result.state, "completed")
        self.assertEqual(self.store.settle_bot_operation(OWNER, job.job_id, success=True).state, "completed")
        with self.assertRaises(JobStateError):
            self.store.settle_bot_operation(OWNER, job.job_id, success=False)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)

    def test_refund_concurrency_and_expiry(self):
        first, _ = self.store.reserve_bot_operation(OWNER, self.digest("first"))
        with self.assertRaises(OperationConcurrencyExceeded):
            self.store.reserve_bot_operation(OWNER, self.digest("second"))
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
        self.store.settle_bot_operation(OWNER, first.job_id, success=False)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 0)
        second, created = self.store.reserve_bot_operation(OWNER, self.digest("second"))
        self.assertTrue(created)
        self.store._db.execute(
            "UPDATE bot_operation_leases SET expires_at=? WHERE job_id=?",
            (time.time() - 1, second.job_id),
        )
        self.assertEqual(self.store.expire_bot_operations(), 1)
        self.assertEqual(self.store.expire_bot_operations(), 0)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 0)
        self.assertEqual(self.store.get(second.job_id, OWNER).state, "failed")
        self.assertEqual(self.store.settle_bot_operation(OWNER, second.job_id, success=False).state, "failed")
        with self.assertRaises(JobStateError):
            self.store.settle_bot_operation(OWNER, second.job_id, success=True)

    def test_restart_refunds_unfinished_bot_operation(self):
        job, _ = self.store.reserve_bot_operation(OWNER, self.digest("restart"))
        self.store.mark_interrupted_failed()
        self.assertEqual(self.store.get(job.job_id, OWNER).state, "failed")
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 0)

    def test_no_quota_for_other_users(self):
        first, _ = self.store.reserve_bot_operation(OWNER, self.digest("same"))
        second, _ = self.store.reserve_bot_operation(OWNER + 1, self.digest("same"))
        self.assertNotEqual(first.job_id, second.job_id)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)
        self.assertEqual(self.store.usage_snapshot(OWNER + 1)["daily_used"], 1)


class BotOperationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self.tmp.name) / "jobs.sqlite3")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        self.patches = [
            patch.object(server, "jobs", self.store),
            patch.object(server, "job_runtime", object()),
            patch.object(server, "get_settings", return_value=SimpleNamespace(bot_token=TOKEN)),
            patch.object(server, "authorize_new_processing", new_callable=AsyncMock, return_value=OWNER),
            patch.object(server, "internal_bot_operation_replay", ReplayGuard()),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.api),
            base_url="http://test.internal",
        )
        self.addAsyncCleanup(self.client.aclose)

    def headers(self, owner, scope, *, token=TOKEN):
        issued = int(time.time())
        nonce = secrets.token_hex(16)
        return {
            "X-FileShape-User": str(owner),
            "X-FileShape-Time": str(issued),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": sign_access_request(
                token, owner, issued, nonce, scope=scope,
            ),
        }

    async def reserve(self, request_id, *, owner=OWNER):
        return await self.client.post(
            "/internal/v1/operations/reserve", json={"request_id": request_id},
            headers=self.headers(owner, "reserve:" + request_id),
        )

    async def settle(self, job_id, success=True, *, owner=OWNER):
        return await self.client.post(
            "/internal/v1/operations/settle",
            json={"job_id": job_id, "success": success},
            headers=self.headers(
                owner, "settle:" + job_id + (":1" if success else ":0"),
            ),
        )

    async def test_signed_reserve_settle_replay_and_quota(self):
        request_id = secrets.token_hex(16)
        first = await self.reserve(request_id)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["state"], "processing")
        job_id = first.json()["job_id"]
        replay = await self.reserve(request_id)
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.json()["created"])
        self.assertEqual(replay.json()["job_id"], job_id)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)
        other = await self.reserve(secrets.token_hex(16))
        self.assertEqual(other.status_code, 429)
        self.assertEqual((await self.settle(job_id, owner=OWNER + 1)).status_code, 404)
        done = await self.settle(job_id)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["state"], "completed")
        self.assertEqual((await self.settle(job_id)).status_code, 200)
        self.assertEqual((await self.settle(job_id, False)).status_code, 409)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 1)

    async def test_scope_tamper_unsigned_and_bounded_body(self):
        request_id = secrets.token_hex(16)
        route = "/internal/v1/operations/reserve"
        self.assertEqual((await self.client.post(route, json={"request_id": request_id})).status_code, 401)
        headers = self.headers(OWNER, "reserve:" + request_id)
        altered = secrets.token_hex(16)
        self.assertEqual((await self.client.post(
            route, json={"request_id": altered}, headers=headers,
        )).status_code, 401)
        wrong_scope = self.headers(OWNER, "settle:" + request_id + ":1")
        self.assertEqual((await self.client.post(
            route, json={"request_id": request_id}, headers=wrong_scope,
        )).status_code, 401)
        self.assertEqual((await self.client.post(
            route, content=b"x" * 513, headers=self.headers(OWNER, "reserve:" + request_id),
        )).status_code, 413)
        self.assertEqual(self.store.usage_snapshot(OWNER)["daily_used"], 0)

    async def test_signed_client_operations_require_configured_service(self):
        with patch.dict(os.environ, {"FILESHAPE_OPERATION_GATE_URL": "", "FILESHAPE_ACCESS_GATE_URL": ""}):
            with self.assertRaises(BotOperationUnavailable):
                await reserve_bot_operation(OWNER, TOKEN)


if __name__ == "__main__":
    unittest.main()
