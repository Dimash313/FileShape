"""Authenticated PDF merge API: full HTTP/worker path and safety regressions.

Creates small PDFs in memory; no Telegram network, external accounts or
long-lived files. The existing process worker handles untrusted parsers.
"""
from io import BytesIO
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from api import server
from api.admission import AdmissionQueue
from api.jobs import JobRegistry
from api.server import api
from api.worker import execute

TOKEN = "987654:pdf-merge-test"
ROUTE = "/api/v1/pdf/merge"


def signed_header(user_id=47001):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


def pdf_fixture(*, pages=1, width=72):
    pdf = PdfWriter()
    for _ in range(pages):
        pdf.add_blank_page(width=width, height=90)
    out = BytesIO()
    pdf.write(out)
    return out.getvalue()


def file_fields(pdfs):
    return [("uploads", (name, data, "application/pdf")) for name, data in pdfs]


class PdfMergeApiTests(unittest.TestCase):
    def setUp(self):
        store = patch.object(server, "jobs", JobRegistry())
        store.start()
        self.addCleanup(store.stop)
        queue = patch.object(server, "admission", AdmissionQueue())
        queue.start()
        self.addCleanup(queue.stop)
        environment = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.headers = signed_header(user_id=47001 + sum(self.id().encode()))

    def upload(self, pdfs, *, auth=True):
        return self.client.post(
            ROUTE,
            headers=self.headers if auth else {},
            files=file_fields(pdfs),
        )

    def test_merge_preserves_upload_order_and_pdf_result(self):
        inputs = [
            ("first.pdf", pdf_fixture(width=72)),
            ("second.PDF", pdf_fixture(pages=2, width=84)),
            ("third.pdf", pdf_fixture(width=96)),
        ]
        response = self.upload(inputs)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("merged.pdf", response.headers["content-disposition"])
        self.assertTrue(response.headers.get("x-fileshape-job-id"))
        reader = PdfReader(BytesIO(response.content))
        self.assertEqual(len(reader.pages), 4)
        self.assertEqual(
            [int(page.mediabox.width) for page in reader.pages], [72, 84, 84, 96],
        )

    def test_two_and_five_pdf_boundaries_work(self):
        inputs = [(f"{i}.pdf", pdf_fixture(width=72 + i)) for i in range(5)]
        for count in (2, 5):
            with self.subTest(count=count):
                response = self.upload(inputs[:count])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(PdfReader(BytesIO(response.content)).pages), count)

    def test_unauthenticated_upload_is_rejected(self):
        response = self.upload([("a.pdf", pdf_fixture()), ("b.pdf", pdf_fixture())],
                               auth=False)
        self.assertEqual(response.status_code, 401)

    def test_invalid_file_count_and_mixed_formats_rejected(self):
        inputs = [(f"{i}.pdf", pdf_fixture()) for i in range(6)]
        for batch in (inputs[:1], inputs):
            with self.subTest(count=len(batch)):
                result = self.upload(batch)
                self.assertEqual(result.status_code, 422, result.text)
        result = self.upload([
            ("a.pdf", pdf_fixture()), ("not_pdf.txt", b"some text"),
        ])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn("PDF", result.json()["detail"])

    def test_spoofed_and_empty_pdf_are_rejected(self):
        cases = (
            [("a.pdf", pdf_fixture()), ("fake.pdf", b"fake content")],
            [("a.pdf", pdf_fixture()), ("empty.pdf", b"")],
            [("a.pdf", pdf_fixture()), ("truncated.pdf", b"%PDF-not-really-a-file")],
        )
        for batch in cases:
            with self.subTest(name=batch[-1][0]):
                response = self.upload(batch)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotEqual(response.headers.get("content-type"), "application/pdf")

    def test_total_uploaded_size_limit_rejected_without_large_fixture(self):
        # Exercise the endpoint's counted-byte check independently of the
        # outer 21 MiB HTTP ingress guard.
        a = pdf_fixture()
        b = pdf_fixture()
        with patch.object(server, "MAX_INPUT_BYTES", len(a) + len(b) - 1):
            result = self.upload([("a.pdf", a), ("b.pdf", b)])
        self.assertEqual(result.status_code, 413, result.text)

    def test_page_limit_and_password_rejections_from_shared_module(self):
        too_many = pdf_fixture(pages=251)
        response = self.upload([("large.pdf", too_many), ("small.pdf", pdf_fixture())])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("page limit", response.json()["detail"].lower())

        encrypted = PdfWriter()
        encrypted.add_blank_page(width=72, height=72)
        encrypted.encrypt("testpassword")
        output = BytesIO()
        encrypted.write(output)
        response = self.upload([("protected.pdf", output.getvalue()),
                                ("normal.pdf", pdf_fixture())])
        self.assertEqual(response.status_code, 422, response.text)

    def test_no_result_workspace_remains_after_delivery(self):
        workspaces = []
        original_workspace = server.Workspace

        def tracked_workspace(*args, **kwargs):
            workspace = original_workspace(*args, **kwargs)
            workspaces.append(Path(workspace.name))
            return workspace

        with patch.object(server, "Workspace", side_effect=tracked_workspace):
            response = self.upload([("a.pdf", pdf_fixture()),
                                    ("b.pdf", pdf_fixture())])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(workspaces), 1)
        self.assertFalse(workspaces[0].exists())

    def test_failed_validation_also_cleans_workspace(self):
        workspaces = []
        original_workspace = server.Workspace

        def tracked_workspace(*args, **kwargs):
            workspace = original_workspace(*args, **kwargs)
            workspaces.append(Path(workspace.name))
            return workspace

        with patch.object(server, "Workspace", side_effect=tracked_workspace):
            response = self.upload([("a.pdf", pdf_fixture()),
                                    ("bad.pdf", b"invalid")])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(workspaces), 1)
        self.assertFalse(workspaces[0].exists())


class PdfMergeWorkerTests(unittest.TestCase):
    def test_reject_unbounded_or_wrong_type_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            for count in (None, 0, 1, 6, True, "2", -1, 1000):
                with self.subTest(count=count):
                    with self.assertRaises(ValueError):
                        execute({"operation": "pdf_merge", "work": folder, "count": count})

    def test_worker_validates_fixed_path_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "pdf_0.pdf").write_bytes(pdf_fixture())
            (path / "pdf_1.pdf").write_bytes(b"not a PDF")
            with self.assertRaises(ValueError):
                execute({"operation": "pdf_merge", "work": folder, "count": 2})
            self.assertFalse((path / "merged.pdf").exists())

    def test_worker_uses_pdf_module_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "pdf_0.pdf").write_bytes(pdf_fixture())
            (path / "pdf_1.pdf").write_bytes(pdf_fixture())
            result = execute({"operation": "pdf_merge", "work": folder, "count": 2})
            self.assertEqual(result["filename"], "merged.pdf")
            self.assertGreater(result["bytes"], 0)
            self.assertEqual(len(PdfReader(path / "merged.pdf").pages), 2)


if __name__ == "__main__":
    unittest.main()
