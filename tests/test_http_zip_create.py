"""Authenticated HTTP ZIP creation: real archive, worker and privacy tests.

Uses small generated binary/text fixtures and the production worker path;
does not rely on Telegram network, external accounts, or persistent uploads.
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
import zipfile

from fastapi.testclient import TestClient

from api import server
from api.admission import AdmissionQueue
from api.jobs import JobRegistry
from api.server import api
from api.worker import execute

TOKEN = "987654:zip-create-contract-test"
ROUTE = "/api/v1/zip/create"


def signed_header(user_id: int = 53001) -> dict[str, str]:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    body = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(values)}


def fields(files: list[tuple[str, bytes]]):
    return [
        ("uploads", (name, data, "application/octet-stream"))
        for name, data in files
    ]


class HttpZipCreateTests(unittest.TestCase):
    def setUp(self):
        registry = patch.object(server, "jobs", JobRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        queue = patch.object(server, "admission", AdmissionQueue())
        queue.start()
        self.addCleanup(queue.stop)
        env = patch.dict(os.environ, {"BOT_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.user_id = 53001 + sum(self.id().encode())
        self.headers = signed_header(self.user_id)

    def upload(self, files, *, auth=True):
        return self.client.post(
            ROUTE,
            headers=self.headers if auth else {},
            files=fields(files),
        )

    def test_creates_valid_zip_with_original_file_order_and_safe_names(self):
        source = [
            ("folder/report.txt", "First".encode("utf-8")),
            ("folder\\report.txt", b"Second"),
            ("other/photo.PNG", b"\x89PNG binary placeholder, general purpose"),
            ("Результаты.txt", "Тест".encode("utf-8")),
        ]
        response = self.upload(source)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("fileshape.zip", response.headers["content-disposition"])
        job_id = response.headers.get("x-fileshape-job-id")
        self.assertTrue(job_id)
        self.assertEqual(server.jobs.get(job_id, self.user_id).state, "completed")

        with zipfile.ZipFile(BytesIO(response.content), "r") as archive:
            self.assertEqual(archive.namelist(), [
                "report.txt", "report_2.txt", "photo.PNG", "Результаты.txt",
            ])
            self.assertEqual(
                [archive.read(name) for name in archive.namelist()],
                [content for _, content in source],
            )
            self.assertTrue(all(
                ".." not in name and not name.startswith("/") and
                "\\" not in name for name in archive.namelist()
            ))

    def test_exactly_two_and_five_files_supported(self):
        files = [(f"file_{index}.bin", bytes([index + 1])) for index in range(5)]
        for count in (2, 5):
            with self.subTest(count=count):
                response = self.upload(files[:count])
                self.assertEqual(response.status_code, 200, response.text)
                with zipfile.ZipFile(BytesIO(response.content)) as archive:
                    self.assertEqual(len(archive.namelist()), count)

    def test_authentication_precedes_upload_processing(self):
        response = self.upload(
            [("first.bin", b"a"), ("second.bin", b"b")], auth=False,
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_file_count_rejected(self):
        files = [(f"f{index}.bin", b"a") for index in range(6)]
        for batch in (files[:1], files):
            with self.subTest(size=len(batch)):
                response = self.upload(batch)
                self.assertEqual(response.status_code, 422, response.text)

    def test_empty_file_and_overlong_filename_rejected(self):
        response = self.upload([("first.bin", b"a"), ("empty.bin", b"")])
        self.assertEqual(response.status_code, 422, response.text)
        response = self.upload([
            ("a" * 256 + ".txt", b"a"), ("second.bin", b"b"),
        ])
        self.assertEqual(response.status_code, 422, response.text)

    def test_aggregate_upload_budget_rejected_by_actual_count(self):
        files = [("first.bin", b"A" * 40), ("second.bin", b"B" * 40)]
        with patch.object(server, "MAX_INPUT_BYTES", 79):
            response = self.upload(files)
        self.assertEqual(response.status_code, 413, response.text)

    def test_large_zip_output_bound_is_checked_after_worker(self):
        files = [("first.bin", b"A" * 20), ("second.bin", b"B" * 20)]
        with patch.object(server, "MAX_RESULT_BYTES", 10):
            response = self.upload(files)
        self.assertEqual(response.status_code, 413, response.text)

    def test_workspace_cleaned_after_success_and_failed_upload(self):
        source_workspace = server.Workspace
        created = []

        def tracking_workspace(*args, **kwargs):
            work = source_workspace(*args, **kwargs)
            self.assertTrue(Path(work.name).name.startswith(
                "fileshape_batch_zip_create_",
            ))
            created.append(Path(work.name))
            return work

        with patch.object(server, "Workspace", side_effect=tracking_workspace):
            ok = self.upload([("a.bin", b"a"), ("b.bin", b"b")])
            invalid = self.upload([("a.bin", b"a"), ("b.bin", b"")])
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(len(created), 2)
        self.assertTrue(all(not path.exists() for path in created))

    def test_later_failure_does_not_leave_usable_output(self):
        source_workspace = server.Workspace
        created = []

        def tracking_workspace(*args, **kwargs):
            work = source_workspace(*args, **kwargs)
            created.append(Path(work.name))
            return work

        with (
            patch.object(server, "Workspace", side_effect=tracking_workspace),
            patch.object(server, "run_managed_worker",
                         side_effect=ValueError("worker refused ZIP")),
        ):
            response = self.upload([("a.bin", b"a"), ("b.bin", b"b")])
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("worker refused ZIP", response.json()["detail"])
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())


class ZipCreateWorkerTests(unittest.TestCase):
    def test_worker_rejects_wrong_count_and_type(self):
        with tempfile.TemporaryDirectory() as folder:
            for count in (None, True, "2", 0, 1, 6, -1, 10_000):
                with self.subTest(count=count):
                    with self.assertRaises(ValueError):
                        execute({
                            "operation": "zip_create", "work": folder,
                            "count": count, "names": ["a.bin", "b.bin"],
                        })

    def test_worker_rejects_invalid_filename_list_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            for names in (
                None, "a.bin", [], ["a.bin"], ["a.bin", None],
                ["a.bin", ""], ["a.bin", "x" * 256],
                ["a.bin", "b.bin", "unexpected"],
            ):
                with self.subTest(names=str(names)[:50]):
                    with self.assertRaises(ValueError):
                        execute({
                            "operation": "zip_create", "work": folder,
                            "count": 2, "names": names,
                        })
            self.assertFalse((Path(folder) / "fileshape.zip").exists())

    def test_worker_rejects_missing_or_symlink_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "zip_item_0").write_bytes(b"local")
            with self.assertRaises(ValueError):
                execute({
                    "operation": "zip_create", "work": folder,
                    "count": 2, "names": ["a.txt", "b.txt"],
                })
            outside = root / "outside"
            outside.write_bytes(b"should not read")
            (root / "zip_item_1").symlink_to(outside)
            with self.assertRaises(ValueError):
                execute({
                    "operation": "zip_create", "work": folder,
                    "count": 2, "names": ["a.txt", "b.txt"],
                })
            self.assertFalse((root / "fileshape.zip").exists())

    def test_worker_refuses_aggregate_size_over_http_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "zip_item_0").write_bytes(b"123")
            (root / "zip_item_1").write_bytes(b"456")
            with patch.object(server, "MAX_INPUT_BYTES", 5):
                with self.assertRaises(ValueError):
                    execute({
                        "operation": "zip_create", "work": folder,
                        "count": 2, "names": ["a.txt", "b.txt"],
                    })
            self.assertFalse((root / "fileshape.zip").exists())

    def test_worker_only_uses_fixed_private_paths_and_shared_archive_module(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "zip_item_0").write_bytes(b"first")
            (root / "zip_item_1").write_bytes(b"second")
            with patch("api.worker.archive_module") as archive:
                def create(inputs, target):
                    self.assertEqual(
                        [p.name for p, _ in inputs],
                        ["zip_item_0", "zip_item_1"],
                    )
                    self.assertEqual(
                        [name for _, name in inputs],
                        ["../first.txt", "nested\\second.txt"],
                    )
                    self.assertEqual(target.name, "fileshape.zip")
                    target.write_bytes(b"PK mock ZIP")
                    return 2

                archive.create.side_effect = create
                result = execute({
                    "operation": "zip_create", "work": folder,
                    "count": 2, "names": ["../first.txt", "nested\\second.txt"],
                })
                archive.create.assert_called_once()
                archive.extract.assert_not_called()
                archive.inspect.assert_not_called()
            self.assertEqual(result["filename"], "fileshape.zip")
            self.assertGreater(result["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
