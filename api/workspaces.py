"""Private, bounded temporary workspaces with crash-recovery cleanup.

Each workspace has a held advisory lock. Startup cleanup skips active locks.
Linux/POSIX only; Windows fallback uses ordinary TemporaryDirectory.
"""
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
import time

ROOT_NAME = "fileshape-workspaces-v1"
STALE_SECONDS = 3600
MAX_SCAN = 500


def workspace_root() -> Path:
    root = Path(tempfile.gettempdir()) / ROOT_NAME
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Invalid workspace root")
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe workspace permissions")
    return root


class Workspace:
    def __init__(self, prefix="fileshape_"):
        self._temp = tempfile.TemporaryDirectory(prefix=prefix, dir=workspace_root())
        self.name = self._temp.name
        self._lock = open(Path(self.name) / ".active.lock", "wb")
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX)

    def cleanup(self):
        if self._temp is not None:
            try:
                self._temp.cleanup()
            finally:
                self._lock.close()
                self._temp = None


def cleanup_orphans(now=None):
    """Remove only old, unlocked workspaces from our private directory."""
    root = workspace_root()
    cutoff = (time.time() if now is None else now) - STALE_SECONDS
    removed = 0
    scanned = 0
    for path in root.iterdir():
        if scanned >= MAX_SCAN:
            break
        scanned += 1
        if path.is_symlink() or not path.is_dir():
            continue
        if not path.name.startswith(("fileshape_api_", "fileshape_batch_")):
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue
            lock_path = path / ".active.lock"
            if lock_path.is_symlink() or not lock_path.is_file():
                continue
            with lock_path.open("rb") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                # Recheck under lock to avoid a race with a recent writer.
                if path.stat().st_mtime <= cutoff:
                    shutil.rmtree(path)
                    removed += 1
        except (OSError, FileNotFoundError):
            continue
    return removed
