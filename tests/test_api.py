"""Telegram HMAC verification and authenticated API smoke tests."""
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
