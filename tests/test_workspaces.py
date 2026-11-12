"""Crash-recovery cleanup must never delete active or recent jobs."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from api.workspaces import Workspace, cleanup_orphans, STALE_SECONDS


@unittest.skipUnless(os.name == "posix", "Requires POSIX advisory locks")
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch("api.workspaces.workspace_root", return_value=Path(self.temp.name))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_active_workspace_survives_cleanup_even_if_old(self):
        job = Workspace(prefix="fileshape_api_")
        self.addCleanup(job.cleanup)
        path = Path(job.name)
        old = time.time() - STALE_SECONDS - 100
        os.utime(path, (old, old))
        self.assertEqual(cleanup_orphans(), 0)
        self.assertTrue(path.exists())

    def test_old_unlocked_workspace_is_removed(self):
        path = Path(self.temp.name) / "fileshape_batch_orphan"
        path.mkdir()
        (path / ".active.lock").write_bytes(b"")
        old = time.time() - STALE_SECONDS - 100
        os.utime(path, (old, old))
        self.assertEqual(cleanup_orphans(), 1)
        self.assertFalse(path.exists())

    def test_recent_unlocked_workspace_is_preserved(self):
        path = Path(self.temp.name) / "fileshape_api_recent"
        path.mkdir()
        (path / ".active.lock").write_bytes(b"")
        self.assertEqual(cleanup_orphans(), 0)
        self.assertTrue(path.exists())

    def test_unknown_directory_is_never_deleted(self):
        path = Path(self.temp.name) / "not_fileshape"
        path.mkdir()
        (path / ".active.lock").write_bytes(b"")
        old = time.time() - STALE_SECONDS - 100
        os.utime(path, (old, old))
        self.assertEqual(cleanup_orphans(), 0)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
