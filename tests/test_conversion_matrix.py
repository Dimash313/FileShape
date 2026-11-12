"""End-to-end conversion matrix through the actual authenticated API and worker.

The test fixtures are small and generated in memory. All results are parsed
to ensure outputs are usable, rather than checking only HTTP 200.
"""
from io import BytesIO
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter

from api.server import api

TOKEN = "987654:testing-token-only"


def signed_header(user_id=910002):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


def image_bytes(fmt):
    buf = BytesIO()
    Image.new("RGB", (24, 18), (20, 100, 200)).save(buf, format=fmt)
    return buf.getvalue()


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=96)
    writer.add_blank_page(width=72, height=96)
    writer.add_blank_page(width=72, height=96)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def docx_bytes():
    doc = Document()
    doc.add_paragraph("FileShape sample text")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class ConversionMatrixTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.headers = signed_header(user_id=910002 + sum(self.id().encode()))

    def convert(self, name, payload, action, pages=""):
        return self.client.post(
            "/api/v1/convert",
            headers=self.headers,
            data={"action": action, "pages": pages},
            files={"upload": (name, payload, "application/octet-stream")},
        )

    def test_image_conversion_matrix(self):
        source = image_bytes("PNG")
        for action, expected in (
            ("img:JPEG", "JPEG"),
            ("img:PNG", "PNG"),
            ("img:WEBP", "WEBP"),
            ("img:PDF", "PDF"),
            ("img:compress", "WEBP"),
        ):
            with self.subTest(action=action):
                response = self.convert("photo.png", source, action)
                self.assertEqual(response.status_code, 200, response.text)
                if expected == "PDF":
                    self.assertEqual(len(PdfReader(BytesIO(response.content)).pages), 1)
                else:
                    with Image.open(BytesIO(response.content)) as result:
                        self.assertEqual(result.format, expected)
                        self.assertEqual(result.size, (24, 18))

    def test_pdf_editing_matrix(self):
        source = pdf_bytes()
        cases = (
            ("pdf:rotate", "", 3),
            ("pdf:first", "", 1),
            ("pdf:extract", "1,3", 2),
            ("pdf:remove", "2", 2),
        )
        for action, pages, count in cases:
            with self.subTest(action=action):
                response = self.convert("pages.pdf", source, action, pages)
                self.assertEqual(response.status_code, 200, response.text)
                reader = PdfReader(BytesIO(response.content))
                self.assertEqual(len(reader.pages), count)
                if action == "pdf:rotate":
                    self.assertEqual(reader.pages[0].get("/Rotate"), 90)
        info = self.convert("pages.pdf", source, "pdf:info")
        self.assertEqual(info.status_code, 200, info.text)
        self.assertEqual(info.json()["info"]["pages"], 3)

    def test_text_and_docx_roundtrip(self):
        source = "Тест FileShape\nВторая строка"
        response = self.convert("source.txt", source.encode(), "txt:docx")
        self.assertEqual(response.status_code, 200, response.text)
        document = Document(BytesIO(response.content))
        self.assertIn("Тест FileShape", document.paragraphs[0].text)
        back = self.convert("result.docx", response.content, "docx:txt")
        self.assertEqual(back.status_code, 200, back.text)
        self.assertIn("Вторая строка", back.content.decode("utf-8"))

    def test_valid_docx_info(self):
        response = self.convert("document.docx", docx_bytes(), "docx:info")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(response.json()["info"]["paragraphs"], 1)


if __name__ == "__main__":
    unittest.main()
