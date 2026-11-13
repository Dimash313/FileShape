"""Single-instance durable metadata lifecycle. Does not persist/replay files."""
import fcntl
import os
from pathlib import Path
import stat

from api.durable_jobs import DurableJobStore


class JobRuntime:
    def __init__(self, directory: str | Path):
        self.store = None
        self._fd = None
        root = Path(directory).absolute()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeError("Job state directory must be private and service-owned")
        # Never unlink this lock: replacing the inode would permit two owners.
        fd = os.open(root / "instance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise RuntimeError("Unsafe instance lock")
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another API process owns this job store; use one worker") from None
            self._fd = fd
            self.store = DurableJobStore(root / "jobs.sqlite3")
            self.store.discard_pending_admissions()
            self.store.mark_interrupted_failed()
            self.store.prune_terminal()
        except BaseException:
            if self.store is not None:
                self.store.close()
            os.close(fd)
            self._fd = None
            raise

    def close(self):
        try:
            if self.store is not None:
                self.store.close()
                self.store = None
        finally:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
