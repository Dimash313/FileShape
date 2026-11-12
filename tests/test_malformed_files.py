"""Real worker regression tests for malformed file inputs.

These use the actual subprocess parser, not mocks. No private files are used.
"""
from io import BytesIO
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from api.admission import AdmissionQueue
from api import server
from api.server import api
from api.worker_runner import run_worker, WorkerFailed

TOKEN = "987654:testing-token-only"


def auth_header():
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 55667788}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


def make_png():
    output = BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, format="PNG")
    return output.getvalue()


def make_zip(files):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


class MalformedFileAPITests(unittest.TestCase):
    def setUp(self):
        # TestClient instances share the imported ASGI app; isolate each
        # request test from shutdown in other app lifecycles.
        queue = patch.object(server, "admission", AdmissionQueue())
        queue.start()
        self.addCleanup(queue.stop)
        self.environment = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.headers = auth_header()

    def convert(self, filename, data, action):
        return self.client.post(
            "/api/v1/convert",
            headers=self.headers,
            data={"action": action},
            files={"upload": (filename, data, "application/octet-stream")},
        )

    def test_truncated_pdf_rejected_then_valid_text_works(self):
        invalid = self.convert("bad.pdf", b"%PDF-1.7\nnot-a-real-document", "pdf:info")
        self.assertEqual(invalid.status_code, 422, invalid.text)
        valid = self.convert("hello.txt", "Привет".encode("utf-8"), "txt:info")
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["info"]["characters"], 6)

    def test_corrupt_png_rejected_and_next_image_converts(self):
        original = make_png()
        invalid = self.convert("truncated.png", original[:40], "img:JPEG")
        self.assertEqual(invalid.status_code, 422, invalid.text)
        valid = self.convert("picture.png", original, "img:JPEG")
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertTrue(valid.content.startswith(b"\xff\xd8\xff"))

    def test_zip_truncated_and_unsafe_paths(self):
        original = make_zip({"hello.txt": "hello"})
        invalid = self.convert("broken.zip", original[:-22], "zip:list")
        self.assertEqual(invalid.status_code, 422, invalid.text)
        unsafe = self.convert("unsafe.zip", make_zip({"../escape.txt": "no"}), "zip:list")
        self.assertEqual(unsafe.status_code, 422, unsafe.text)
        valid = self.convert("valid.zip", original, "zip:list")
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["info"]["files"], 1)

    def test_docx_container_missing_word_document(self):
        invalid = self.convert("not_word.docx", make_zip({"file.txt": "hello"}), "docx:info")
        self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_invalid_utf8_txt(self):
        invalid = self.convert("invalid.txt", b"\xff\xfe\x80hello", "txt:info")
        self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_corrupt_batch_does_not_break_next_batch(self):
        valid = make_png()
        files = [
            ("uploads", ("first.png", valid, "image/png")),
            ("uploads", ("second.png", valid[:40], "image/png")),
        ]
        invalid = self.client.post("/api/v1/images/pdf", headers=self.headers, files=files)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        good_files = [
            ("uploads", ("first.png", valid, "image/png")),
            ("uploads", ("second.png", valid, "image/png")),
        ]
        good = self.client.post("/api/v1/images/pdf", headers=self.headers, files=good_files)
        self.assertEqual(good.status_code, 200, good.text)
        self.assertTrue(good.content.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
