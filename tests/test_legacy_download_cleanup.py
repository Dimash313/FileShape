"""Legacy HTTP result deadlines and disconnects must not retain locked files."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from starlette.background import BackgroundTask

from api.server import BoundedFileResponse
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

    async def test_legacy_stalled_download_has_deadline_and_cleans_workspace(self):
        await self.exercise(timeout=True)

    async def test_legacy_disconnect_also_cleans_workspace(self):
        await self.exercise(timeout=False)
