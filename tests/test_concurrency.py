"""Real ASGI concurrency tests for FileShape admission and slot recovery.

No external services are used. The expensive worker is replaced with a
controllable async stub so overload behavior is deterministic.
"""
import asyncio
from collections import defaultdict, deque
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from io import BytesIO
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from api.jobs import JobRegistry
from api.admission import AdmissionQueue
from api.server import api
from api import server
TOKEN = "987654:testing-token-only"


def signed_init_data(user_id: int) -> str:
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(output, format="PNG")
    return output.getvalue()


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        registry = patch.object(server, "jobs", JobRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        # A fresh semaphore is required for each IsolatedAsyncioTestCase event loop.
        capacity = patch.object(server, 'slots', asyncio.Semaphore(3))
        capacity.start()
        self.addCleanup(capacity.stop)
        queue = patch.object(server, 'admission', AdmissionQueue(max_waiters=1, wait_seconds=3))
        queue.start()
        self.addCleanup(queue.stop)
        limits = patch.object(server, 'recent_requests', defaultdict(deque))
        limits.start()
        self.addCleanup(limits.stop)
        self.environment = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api),
            base_url="http://fileshape.test",
            timeout=8,
        )
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"X-Telegram-Init-Data": signed_init_data(user_id=987654321)}
        self.image = png_bytes()

    async def submit(self):
        return await self.client.post(
            "/api/v1/convert",
            headers=self.headers,
            data={"action": "img:JPEG"},
            files={"upload": ("photo.png", self.image, "image/png")},
        )

    async def test_fourth_request_waits_while_three_are_processing(self):
        entered = 0
        peak = 0
        active = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked_worker(payload):
            nonlocal entered, peak, active
            entered += 1
            active += 1
            peak = max(peak, active)
            if entered == 3:
                started.set()
            try:
                await release.wait()
                target = Path(payload["work"]) / "converted.jpg"
                target.write_bytes(b"jpeg-test-output")
                return {"ok": True, "filename": target.name}
            finally:
                active -= 1

        with patch("api.server.run_worker", side_effect=blocked_worker):
            tasks = [asyncio.create_task(self.submit()) for _ in range(3)]
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                fourth_task = asyncio.create_task(self.submit())
                for _ in range(150):
                    if server.admission.waiting == 1:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(server.admission.waiting, 1)
                self.assertFalse(fourth_task.done())
                self.assertEqual(entered, 3)
                self.assertEqual(peak, 3)
            finally:
                release.set()
                responses = await asyncio.gather(*tasks, fourth_task)
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(active, 0)
        self.assertEqual(server.slots._value, 3)

    async def test_batch_and_single_share_capacity_and_recover(self):
        entered = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked_worker(payload):
            nonlocal entered
            entered += 1
            if entered == 3:
                started.set()
            await release.wait()
            directory = Path(payload["work"])
            if payload["operation"] == "batch":
                (directory / "fileshape_photos.pdf").write_bytes(b"%PDF-1.4\\n%%EOF")
                return {"ok": True}
            target = directory / "converted.jpg"
            target.write_bytes(b"jpeg-test-output")
            return {"ok": True, "filename": target.name}

        async def submit_batch():
            return await self.client.post(
                "/api/v1/images/pdf",
                headers=self.headers,
                files=[
                    ("uploads", ("one.png", self.image, "image/png")),
                    ("uploads", ("two.png", self.image, "image/png")),
                ],
            )

        with patch("api.server.run_worker", side_effect=blocked_worker):
            tasks = [asyncio.create_task(self.submit()),
                     asyncio.create_task(submit_batch()),
                     asyncio.create_task(self.submit())]
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                fourth_task = asyncio.create_task(submit_batch())
                for _ in range(150):
                    if server.admission.waiting == 1:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(server.admission.waiting, 1)
                self.assertEqual(entered, 3)
                rejected = await self.submit()
                self.assertEqual(rejected.status_code, 429, rejected.text)
                self.assertEqual(rejected.headers.get("retry-after"), "15")
            finally:
                release.set()
                responses = await asyncio.gather(*tasks, fourth_task)
        self.assertEqual([r.status_code for r in responses], [200, 200, 200, 200])
        self.assertEqual(server.slots._value, 3)

    async def test_worker_cancellation_restores_capacity(self):
        started = asyncio.Event()

        async def hanging_worker(payload):
            started.set()
            await asyncio.Event().wait()

        with patch("api.server.run_worker", side_effect=hanging_worker):
            task = asyncio.create_task(self.submit())
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(server.slots._value, 3)

    async def test_failed_worker_releases_slot(self):
        async def failed_worker(payload):
            raise ValueError("invalid document")

        with patch("api.server.run_worker", side_effect=failed_worker):
            response = await self.submit()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(server.slots._value, 3)

    async def test_subsequent_request_succeeds_after_failure(self):
        async def good_worker(payload):
            target = Path(payload["work"]) / "converted.jpg"
            target.write_bytes(b"jpeg-test-output")
            return {"ok": True, "filename": target.name}

        with patch("api.server.run_worker", side_effect=ValueError("bad file")):
            self.assertEqual((await self.submit()).status_code, 422)
        with patch("api.server.run_worker", side_effect=good_worker):
            self.assertEqual((await self.submit()).status_code, 200)
        self.assertEqual(server.slots._value, 3)


if __name__ == "__main__":
    unittest.main()
