"""Telegram HMAC verification and authenticated API smoke tests."""
import asyncio
import hashlib
import hmac
from io import BytesIO
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from PIL import Image

from api.auth import InvalidInitData, verify_init_data
from api.admission import AdmissionQueue
from api.jobs import JobRegistry
from api import server
from api.server import api

TOKEN = "987654:testing-token-only"


def signed_init_data(user_id: int = 1001, auth_date: int | None = None) -> str:
    data = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class TelegramAuthTests(unittest.TestCase):
    def test_valid_signature(self):
        self.assertEqual(verify_init_data(signed_init_data(), TOKEN), 1001)

    def test_reject_tampered_and_expired(self):
        raw = signed_init_data()
        with self.assertRaises(InvalidInitData):
            verify_init_data(raw.replace("1001", "1002"), TOKEN)
        with self.assertRaises(InvalidInitData):
            verify_init_data(signed_init_data(auth_date=int(time.time()) - 3601), TOKEN)
        with self.assertRaises(InvalidInitData):
            verify_init_data(signed_init_data(), "wrong-token")
        with self.assertRaises(InvalidInitData):
            verify_init_data("", TOKEN)

    def test_reject_duplicate_signed_parameter(self):
        with self.assertRaises(InvalidInitData):
            verify_init_data(signed_init_data() + "&user=other", TOKEN)


class APITests(unittest.TestCase):
    def setUp(self):
        # TestClient instances share the imported ASGI app; isolate each
        # request test from shutdown in other app lifecycles.
        queue = patch.object(server, "admission", AdmissionQueue())
        queue.start()
        self.addCleanup(queue.stop)
        registry = patch.object(server, "jobs", JobRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        self.env = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.auth = {"X-Telegram-Init-Data": signed_init_data(user_id=12345)}

    def test_health_and_private_session(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)
        result = self.client.get("/api/v1/session", headers=self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["user_id"], 12345)

    def test_job_status_requires_auth_and_owner(self):
        job = server.jobs.create(12345)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job.job_id}").status_code, 401)
        found = self.client.get(f"/api/v1/jobs/{job.job_id}", headers=self.auth)
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["state"], "queued")
        self.assertEqual(found.headers.get("cache-control"), "no-store")
        other = {"X-Telegram-Init-Data": signed_init_data(user_id=99999)}
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job.job_id}", headers=other).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/jobs/nonexistent", headers=self.auth).status_code, 404)

    def test_queue_status_requires_auth_and_omits_user_data(self):
        self.assertEqual(self.client.get("/api/v1/queue").status_code, 401)
        response = self.client.get("/api/v1/queue", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(set(response.json()), {
            "capacity", "active", "waiting", "waiting_limit", "accepting",
        })
        self.assertEqual(response.json()["capacity"], server.MAX_CONCURRENT_JOBS)
        self.assertNotIn("user", response.text)
        self.assertNotIn("filename", response.text)

    def test_queue_status_reports_live_load_and_shutdown(self):
        capacity = server.MAX_CONCURRENT_JOBS
        with patch.object(server, "slots", asyncio.Semaphore(capacity)):
            self.assertGreaterEqual(capacity, 1)
            await_slots = server.slots
            await_slots._value = capacity - 1
            server.admission.waiting = 2
            response = self.client.get("/api/v1/queue", headers=self.auth)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["active"], 1)
            self.assertEqual(response.json()["waiting"], 2)
            self.assertTrue(response.json()["accepting"])
            server.admission.close()
            closed = self.client.get("/api/v1/queue", headers=self.auth)
            self.assertEqual(closed.status_code, 200)
            self.assertFalse(closed.json()["accepting"])

    def test_convert_image_and_stream_result(self):
        image = Image.new("RGB", (12, 12), "blue")
        raw = BytesIO()
        image.save(raw, format="PNG")
        raw.seek(0)
        response = self.client.post(
            "/api/v1/convert",
            headers=self.auth,
            data={"action": "img:JPEG"},
            files={"upload": ("original.png", raw, "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content.startswith(b"\xff\xd8\xff"))
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_reject_spoofed_pdf_before_parser(self):
        response = self.client.post(
            "/api/v1/convert",
            headers=self.auth,
            data={"action": "pdf:info"},
            files={"upload": ("report.pdf", b"not really a PDF", "application/pdf")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("PDF", response.json()["detail"])

    def test_reject_spoofed_image_in_batch(self):
        valid = BytesIO()
        Image.new("RGB", (10, 10), "white").save(valid, format="PNG")
        response = self.client.post(
            "/api/v1/images/pdf",
            headers=self.auth,
            files=[
                ("uploads", ("first.png", valid.getvalue(), "image/png")),
                ("uploads", ("fake.png", b"not an image", "image/png")),
            ],
        )
        self.assertEqual(response.status_code, 422)

    def test_reject_invalid_operation(self):
        response = self.client.post(
            "/api/v1/convert",
            headers=self.auth,
            data={"action": "pdf:remove"},
            files={"upload": ("file.txt", b"hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 422)

    def test_reject_file_without_authentication(self):
        response = self.client.post(
            "/api/v1/convert",
            data={"action": "txt:info"},
            files={"upload": ("file.txt", b"hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 401)

    def test_batch_images_pdf(self):
        from pypdf import PdfReader
        from io import BytesIO as Stream
        sources = []
        for size in ((14, 12), (24, 16), (20, 21)):
            image = Image.new("RGB", size, "white")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            sources.append(buffer.getvalue())
        response = self.client.post(
            "/api/v1/images/pdf",
            headers=self.auth,
            files=[("uploads", (f"image_{i}.png", item, "image/png")) for i, item in enumerate(sources)],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(PdfReader(Stream(response.content)).pages), 3)
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_batch_requires_2_to_8_images(self):
        response = self.client.post(
            "/api/v1/images/pdf",
            headers=self.auth,
            files=[("uploads", ("one.png", b"x", "image/png"))],
        )
        self.assertEqual(response.status_code, 422)

    def test_batch_requires_telegram_auth(self):
        response = self.client.post(
            "/api/v1/images/pdf",
            files=[("uploads", ("one.png", b"x", "image/png")), ("uploads", ("two.png", b"x", "image/png"))],
        )
        self.assertEqual(response.status_code, 401)

    def test_batch_rejects_non_images(self):
        response = self.client.post(
            "/api/v1/images/pdf",
            headers=self.auth,
            files=[("uploads", ("one.png", b"x", "image/png")), ("uploads", ("two.txt", b"x", "text/plain"))],
        )
        self.assertEqual(response.status_code, 422)

    def test_broken_zip_cannot_be_listed(self):
        response = self.client.post(
            "/api/v1/convert",
            headers=self.auth,
            data={"action": "zip:list"},
            files={"upload": ("file.zip", b"not a zip", "application/zip")},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
