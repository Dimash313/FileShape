"""Legacy HTTP result deadlines and disconnects must not retain locked files."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from starlette.background import BackgroundTask

from api.server import BoundedFileResponse, _legacy_result_preflight, MAX_RESULT_BYTES
from api.workspaces import Workspace


class LegacyDownloadCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, timeout):
        with tempfile.TemporaryDirectory() as directory, patch('api.workspaces.workspace_root', return_value=Path(directory)):
            work = Workspace(prefix='fileshape_api_')
            marker_lock = work._lock
            target = Path(work.name) / 'result.txt'
            target.write_bytes(b'finished file')
            calls = []
            def cleanup():
                calls.append(True)
                work.cleanup()
            response = BoundedFileResponse(target, background=BackgroundTask(cleanup))
            response.timeout_seconds = 0.02
            async def send(event):
                if event['type'] == 'http.response.body':
                    if timeout:
                        await asyncio.Event().wait()
                    raise OSError('client disconnected')
            async def receive():
                return {'type': 'http.disconnect'}
            scope = {'type':'http', 'method':'GET', 'headers':[], 'extensions':{},
                     'asgi':{'version':'3.0','spec_version':'2.4'}}
            with self.assertRaises(TimeoutError if timeout else OSError):
                await response(scope, receive, send)
            self.assertEqual(len(calls), 1)
            self.assertFalse(Path(work.name).exists())
            self.assertTrue(marker_lock.closed)

    async def capture_response(self, response, *, method="GET", headers=(), pathsend=False):
        events = []

        async def send(event):
            events.append(event)

        async def receive():
            return {"type": "http.disconnect"}

        extensions = {"http.response.pathsend": {}} if pathsend else {}
        scope = {
            "type": "http", "method": method, "headers": list(headers),
            "extensions": extensions,
            "asgi": {"version": "3.0", "spec_version": "2.4"},
        }
        await response(scope, receive, send)
        return events

    async def test_replaced_output_symlink_cannot_change_bytes_after_open(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "api.workspaces.workspace_root", return_value=Path(directory)
        ):
            secret = Path(directory) / "outside.txt"
            secret.write_bytes(b"SECRET OUTSIDE WORKSPACE")
            work = Workspace(prefix="fileshape_api_")
            target = Path(work.name) / "result.txt"
            target.write_bytes(b"safe result")
            response = BoundedFileResponse(
                target, dir_fd=work._directory_fd,
                filename="result.txt", background=BackgroundTask(work.cleanup),
                headers={"Cache-Control": "no-store"},
            )
            fd = int(str(response.path).rsplit("/", 1)[1])
            # Malformed/compromised worker replaces the pathname after
            # handler validation. The response must serve the pinned inode.
            target.unlink()
            target.symlink_to(secret)
            events = await self.capture_response(response, pathsend=True)
            self.assertEqual(events[0]["status"], 200)
            self.assertEqual(
                b"".join(event.get("body", b"") for event in events),
                b"safe result",
            )
            self.assertFalse(any(event["type"] == "http.response.pathsend" for event in events))
            self.assertEqual(secret.read_bytes(), b"SECRET OUTSIDE WORKSPACE")
            self.assertFalse(Path(work.name).exists())
            self.assertFalse(response._pin_finalizer.alive)
            with self.assertRaises(OSError):
                os.fstat(fd)

    async def test_symlink_and_hardlink_results_rejected_before_send(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "api.workspaces.workspace_root", return_value=Path(directory)
        ):
            secret = Path(directory) / "outside.txt"
            secret.write_bytes(b"private")
            work = Workspace(prefix="fileshape_api_")
            self.addCleanup(work.cleanup)
            target = Path(work.name) / "result.txt"
            target.symlink_to(secret)
            with self.assertRaises(ValueError):
                BoundedFileResponse(target, dir_fd=work._directory_fd)
            target.unlink()
            os.link(secret, target)
            with self.assertRaises(ValueError):
                BoundedFileResponse(target, dir_fd=work._directory_fd)
            self.assertEqual(secret.read_bytes(), b"private")

    def test_preflight_never_follows_symlink_and_preserves_413(self):
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.txt"
            outside.write_bytes(b"secret")
            target = root / "result.txt"
            target.symlink_to(outside)
            with self.assertRaises(ValueError):
                _legacy_result_preflight(target, "Результат недоступен")
            target.unlink()
            os.link(outside, target)
            with self.assertRaises(ValueError):
                _legacy_result_preflight(target, "Результат недоступен")
            target.unlink()
            target.write_bytes(b"valid")
            _legacy_result_preflight(target, "Результат недоступен")
            with target.open("r+b") as stream:
                stream.truncate(MAX_RESULT_BYTES + 1)
            with self.assertRaises(HTTPException) as failure:
                _legacy_result_preflight(target, "Результат недоступен")
            self.assertEqual(failure.exception.status_code, 413)

    async def test_range_and_head_keep_existing_file_response_contract(self):
        for method, headers, expected_status, expected_body in (
            ("GET", (), 200, b"abcdef"),
            ("HEAD", (), 200, b""),
            ("GET", ((b"range", b"bytes=1-3"),), 206, b"bcd"),
        ):
            with self.subTest(method=method, headers=headers):
                with tempfile.TemporaryDirectory() as directory, patch(
                    "api.workspaces.workspace_root", return_value=Path(directory)
                ):
                    work = Workspace(prefix="fileshape_api_")
                    target = Path(work.name) / "result.txt"
                    target.write_bytes(b"abcdef")
                    response = BoundedFileResponse(
                        target, dir_fd=work._directory_fd, filename="result.txt",
                        background=BackgroundTask(work.cleanup),
                    )
                    events = await self.capture_response(
                        response, method=method, headers=headers, pathsend=True
                    )
                    self.assertEqual(events[0]["status"], expected_status)
                    body = b"".join(e.get("body", b"") for e in events)
                    self.assertEqual(body, expected_body)
                    self.assertFalse(any(e["type"] == "http.response.pathsend" for e in events))
                    self.assertFalse(Path(work.name).exists())
                    self.assertFalse(response._pin_finalizer.alive)
                    headers_out = dict(events[0]["headers"])
                    self.assertIn(b"content-length", headers_out)
                    self.assertIn(b"content-disposition", headers_out)
                    if expected_status == 206:
                        self.assertEqual(headers_out[b"content-range"], b"bytes 1-3/6")

    async def test_legacy_stalled_download_has_deadline_and_cleans_workspace(self):
        await self.exercise(timeout=True)

    async def test_legacy_disconnect_also_cleans_workspace(self):
        await self.exercise(timeout=False)
