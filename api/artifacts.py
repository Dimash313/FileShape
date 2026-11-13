"""Private, quota-reserved background artifacts with a finite per-boot lifetime.

Authorization belongs to the API before opening a result. Reservations include
input plus worst-case output, then completed files, and stay charged while a
result is leased by an open download. The logical byte budget is separate from
filesystem overhead, which is bounded by the entry limit. This module
never resumes work or promises downloads after a process restart.
"""
from dataclasses import dataclass
import fcntl
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time

from api.workspaces import workspace_root

MAX_RESULT_BYTES = 45 * 1024 * 1024
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{32}\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MIME = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")


class ArtifactCapacity(Exception):
    """No artifact reservation or entry is available."""


class ArtifactUnavailable(Exception):
    """The requested result is absent, expired or unsafe."""


@dataclass
class Artifact:
    path: Path
    reserved_bytes: int
    filename: str | None = None
    content_type: str | None = None
    expires_at: float | None = None
    _leases: int = 0
    _discarded: bool = False


class ArtifactLease:
    """File proxy that releases its byte reservation only after the fd closes."""
    def __init__(self, stream, store, job_id, item):
        self._stream = stream
        self._store = store
        self._job_id = job_id
        self._item = item
        self._released = False

    def read(self, size=-1):
        return self._stream.read(size)

    @property
    def closed(self):
        return self._stream.closed

    def close(self):
        with self._store._lock:
            if self._released:
                return
            self._released = True
            try:
                self._stream.close()
            finally:
                self._store._release(self._job_id, self._item)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._stream)

    def fileno(self):
        return self._stream.fileno()

    def seek(self, *args):
        return self._stream.seek(*args)

    def tell(self):
        return self._stream.tell()


class ArtifactStore:
    def __init__(self, root: Path | None = None, *, max_bytes: int = 256 * 1024 * 1024,
                 max_entries: int = 1000, ttl: float = 3600):
        if (type(max_bytes) is not int or max_bytes < 1 or
                type(max_entries) is not int or max_entries < 1 or
                not math.isfinite(ttl) or ttl <= 0):
            raise ValueError("Invalid artifact settings")
        parent = Path(root) if root is not None else workspace_root()
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private_directory(parent)
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl = ttl
        self._entries: dict[str, Artifact] = {}
        self._reserved = 0
        self._lock = threading.RLock()
        self._closed = False
        self._temp = tempfile.TemporaryDirectory(prefix="fileshape_background_", dir=parent)
        self.path = Path(self._temp.name)
        self._root_fd = None
        self._lock_fd = None
        try:
            self._root_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._lock_fd = os.open(".active.lock", os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                                    0o600, dir_fd=self._root_fd)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
            if self._root_fd is not None:
                os.close(self._root_fd)
            self._temp.cleanup()
            raise

    @staticmethod
    def _private_directory(path):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or
                info.st_mode & 0o077):
            raise ValueError("Artifact directory must be private and service-owned")

    @staticmethod
    def _job_id(job_id):
        if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
            raise ArtifactUnavailable()

    def _open_directory(self, job_id):
        fd = os.open(job_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self._root_fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ArtifactUnavailable()
            return fd
        except BaseException:
            os.close(fd)
            raise

    @property
    def reserved_bytes(self):
        with self._lock:
            return self._reserved

    @property
    def count(self):
        with self._lock:
            return len(self._entries)

    def reserve(self, job_id: str, reservation_bytes: int) -> Artifact:
        self._job_id(job_id)
        if type(reservation_bytes) is not int or reservation_bytes <= 0:
            raise ValueError("Invalid artifact reservation")
        with self._lock:
            if self._closed:
                raise ArtifactUnavailable()
            self.prune()
            if job_id in self._entries:
                raise ValueError("Duplicate artifact reservation")
            if len(self._entries) >= self.max_entries or self._reserved + reservation_bytes > self.max_bytes:
                raise ArtifactCapacity()
            os.mkdir(job_id, mode=0o700, dir_fd=self._root_fd)
            item = Artifact(self.path / job_id, reservation_bytes)
            self._entries[job_id] = item
            self._reserved += reservation_bytes
            return item

    def complete(self, job_id: str, filename: str, content_type: str) -> None:
        self._job_id(job_id)
        if (not isinstance(filename, str) or _FILENAME.fullmatch(filename) is None or ".." in filename or
                not isinstance(content_type, str) or len(content_type) > 128 or _MIME.fullmatch(content_type) is None):
            raise ArtifactUnavailable()
        with self._lock:
            item = self._entries.get(job_id)
            if self._closed or item is None or item.expires_at is not None:
                raise ArtifactUnavailable()
            directory = None
            result = None
            try:
                directory = self._open_directory(job_id)
                result = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                info = os.fstat(result)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                        not 0 < info.st_size <= MAX_RESULT_BYTES):
                    raise ArtifactUnavailable()
                # Worker output plus retained input must fit the accepted reservation.
                total = 0
                with os.scandir(directory) as files:
                    for entry in files:
                        current = entry.stat(follow_symlinks=False)
                        if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.geteuid() or
                                current.st_nlink != 1):
                            raise ArtifactUnavailable()
                        total += current.st_size
                        if total > item.reserved_bytes:
                            raise ArtifactCapacity()
                os.fchmod(result, 0o600)
                item.filename = filename
                item.content_type = content_type
                item.expires_at = time.monotonic() + self.ttl
                self._reserved -= item.reserved_bytes - total
                item.reserved_bytes = total
            except OSError as exc:
                raise ArtifactUnavailable() from exc
            finally:
                if result is not None:
                    os.close(result)
                if directory is not None:
                    os.close(directory)

    def open_result(self, job_id: str):
        """Open before releasing the lock; an fd survives subsequent expiry/unlink."""
        self._job_id(job_id)
        with self._lock:
            item = self._entries.get(job_id)
            if self._closed or item is None or item.expires_at is None or item._discarded:
                raise ArtifactUnavailable()
            if time.monotonic() >= item.expires_at:
                self.discard(job_id)
                raise ArtifactUnavailable()
            directory = None
            result = None
            try:
                directory = self._open_directory(job_id)
                result = os.open(item.filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                info = os.fstat(result)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                        info.st_mode & 0o077 or not 0 < info.st_size <= MAX_RESULT_BYTES or
                        info.st_size > item.reserved_bytes):
                    raise ArtifactUnavailable()
                stream = os.fdopen(result, "rb")
                result = None
                item._leases += 1
                lease = ArtifactLease(stream, self, job_id, item)
                return lease, info.st_size, item.content_type, item.filename
            except OSError as exc:
                raise ArtifactUnavailable() from exc
            finally:
                if result is not None:
                    os.close(result)
                if directory is not None:
                    os.close(directory)

    def _delete(self, job_id, item):
        # rmtree refuses directory symlinks; never follow an injected target.
        try:
            shutil.rmtree(item.path)
        except FileNotFoundError:
            pass
        self._entries.pop(job_id)
        self._reserved -= item.reserved_bytes

    def _release(self, job_id, item):
        with self._lock:
            item._leases -= 1
            if self._closed and not any(entry._leases for entry in self._entries.values()):
                self._finish_close()
                self._entries.clear()
                self._reserved = 0
            elif item._leases == 0 and item._discarded:
                self._delete(job_id, item)

    def discard(self, job_id: str) -> None:
        self._job_id(job_id)
        with self._lock:
            item = self._entries.get(job_id)
            if item is None:
                return
            item._discarded = True
            if item._leases == 0:
                self._delete(job_id, item)

    def prune(self) -> int:
        with self._lock:
            now = time.monotonic()
            expired = [job_id for job_id, item in self._entries.items()
                       if ((item._discarded and item._leases == 0) or
                           (not item._discarded and item.expires_at is not None and now >= item.expires_at))]
            for job_id in expired:
                self.discard(job_id)
            return len(expired)

    def _finish_close(self):
        self._temp.cleanup()
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if not any(item._leases for item in self._entries.values()):
                self._finish_close()
                self._entries.clear()
                self._reserved = 0
            else:
                for job_id in tuple(self._entries):
                    self.discard(job_id)
