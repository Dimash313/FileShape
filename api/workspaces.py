"""Private, bounded temporary workspaces with crash-recovery cleanup.

Each workspace holds directory and marker advisory locks. Cleanup skips active locks.
Linux/POSIX only; advisory locking and fd-relative cleanup are required.
"""
import fcntl
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import threading
import weakref

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
        self._lock = None
        self._directory_fd = None
        self._descriptor_finalizer = None
        fd = None
        try:
            self._directory_fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            fcntl.flock(self._directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open(".active.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self._directory_fd)
            self._lock = os.fdopen(fd, "wb")
            fd = None
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX)
            # The callback retains only the file and fd, never a bound method
            # or self. Losing a workspace must not pin its directory lock.
            self._descriptor_finalizer = weakref.finalize(
                self, Workspace._release_locks, self._lock, self._directory_fd,
            )
        except BaseException:
            try:
                if fd is not None:
                    os.close(fd)
                self._temp.cleanup()
            finally:
                self._close_locks()
                self._temp = None
            raise

    @staticmethod
    def _release_locks(lock, directory_fd):
        try:
            if lock is not None:
                lock.close()
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def _close_locks(self):
        lock, self._lock = self._lock, None
        directory_fd, self._directory_fd = self._directory_fd, None
        if self._descriptor_finalizer is not None:
            # Calling a finalizer detaches it before invoking the callback.
            # Repeated cleanup/GC cannot later close a reused descriptor.
            self._descriptor_finalizer()
        else:
            # Constructor failure before finalizer registration still owns
            # any successfully opened descriptors and must release them.
            self._release_locks(lock, directory_fd)

    def cleanup(self):
        if self._temp is not None:
            try:
                self._temp.cleanup()
            finally:
                self._close_locks()
                self._temp = None


class OrphanCleaner:
    """One owner's bounded, resumable sweep of a private workspace root.

    Keep an instance for periodic cleanup and close it at application shutdown.
    At most one scandir cursor and one parent fd stay open between batches;
    there is no global cursor cache. Directory iteration order is opaque, so
    retaining the iterator (including buffered entries) avoids both rescanning
    an arbitrarily large prefix and skipping buffered directory entries.
    """
    def __init__(self, root: Path | None = None, max_scan: int = MAX_SCAN):
        if type(max_scan) is not int or not 1 <= max_scan <= MAX_SCAN:
            raise ValueError("Invalid orphan scan limit")
        self._configured_root = Path(root).absolute() if root is not None else None
        self.max_scan = max_scan
        self._guard = threading.Lock()
        self._closed = False
        self._iterator = None
        self._root_fd = None
        self._root_path = None
        self._root_identity = None
        self._cursor_finalizer = None

    @staticmethod
    def _private_directory(info):
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077)

    @staticmethod
    def _owned_regular_lock(info):
        return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.geteuid())

    @staticmethod
    def _private_lock(info):
        return OrphanCleaner._owned_regular_lock(info) and not info.st_mode & 0o077

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino

    @staticmethod
    def _release_cursor(iterator, fd):
        try:
            if iterator is not None:
                iterator.close()
        finally:
            if fd is not None:
                os.close(fd)

    def _reset_cursor(self):
        iterator, self._iterator = self._iterator, None
        fd, self._root_fd = self._root_fd, None
        finalizer, self._cursor_finalizer = self._cursor_finalizer, None
        self._root_path = None
        self._root_identity = None
        if finalizer is not None:
            finalizer()
        else:
            self._release_cursor(iterator, fd)

    def _ensure_cursor(self):
        root = self._configured_root if self._configured_root is not None else workspace_root()
        info = root.lstat()
        if not self._private_directory(info):
            raise ValueError("Workspace root must be private and service-owned")
        if (self._iterator is not None and self._root_path == root
                and self._root_identity == self._identity(info)):
            return
        self._reset_cursor()
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not self._private_directory(info):
                raise ValueError("Workspace root must be private and service-owned")
            iterator = os.scandir(fd)
        except BaseException:
            os.close(fd)
            raise
        self._root_fd = fd
        self._iterator = iterator
        self._root_path = root
        self._root_identity = self._identity(info)
        self._cursor_finalizer = weakref.finalize(
            self, OrphanCleaner._release_cursor, iterator, fd,
        )

    def _remove_if_stale(self, entry, cutoff):
        if not entry.name.startswith(("fileshape_api_", "fileshape_batch_", "fileshape_background_")):
            return False
        directory = None
        lock_fd = None
        try:
            # All paths remain relative to the pinned, validated private root.
            # O_NOFOLLOW rejects directory/lock symlinks without a check/open
            # race; O_NONBLOCK prevents a substituted FIFO from hanging cleanup.
            directory = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=self._root_fd)
            info = os.fstat(directory)
            if not self._private_directory(info) or info.st_mtime > cutoff:
                return False
            # The directory lock survives a lost/deleted marker. Production
            # enters this protocol only after exclusive runtime ownership;
            # still honor old marker-only locks for compatible legacy roots.
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                lock_fd = os.open(".active.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=directory)
            except FileNotFoundError:
                # A failed rmtree can have removed the marker before failing.
                # Only an old, private, directory-locked generation may proceed.
                lock_fd = None
            if lock_fd is not None:
                lock_info = os.fstat(lock_fd)
                if not self._owned_regular_lock(lock_info):
                    return False
                # Older Workspace versions inherited the process umask (often
                # producing 0644). Tighten only the verified regular single-link
                # inode, never a linked/special/foreign lock.
                os.fchmod(lock_fd, 0o600)
                lock_info = os.fstat(lock_fd)
                if not self._private_lock(lock_info):
                    return False
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                named_lock = os.stat(".active.lock", dir_fd=directory, follow_symlinks=False)
                if (not self._private_lock(named_lock)
                        or self._identity(named_lock) != self._identity(lock_info)):
                    return False
            else:
                try:
                    os.stat(".active.lock", dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    return False
            named_directory = os.stat(entry.name, dir_fd=self._root_fd, follow_symlinks=False)
            current = os.fstat(directory)
            if (not self._private_directory(named_directory)
                    or self._identity(named_directory) != self._identity(info)
                    or current.st_mtime > cutoff or named_directory.st_mtime > cutoff):
                return False
            # CPython's fd-based rmtree refuses substituted directory symlinks
            # and uses fd-relative traversal on this supported POSIX platform.
            shutil.rmtree(entry.name, dir_fd=self._root_fd)
            return True
        except OSError:
            # Missing, busy, unsafe and partially removed entries stay eligible
            # for a later pass; never change unrelated/active data on an error.
            return False
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            if directory is not None:
                os.close(directory)

    def sweep(self, now=None):
        """Examine at most max_scan entries, continuing next time after them."""
        timestamp = time.time() if now is None else now
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError("Invalid cleanup time")
        cutoff = timestamp - STALE_SECONDS
        with self._guard:
            if self._closed:
                return 0
            try:
                self._ensure_cursor()
                removed = 0
                for _ in range(self.max_scan):
                    try:
                        entry = next(self._iterator)
                    except StopIteration:
                        self._reset_cursor()
                        break
                    removed += int(self._remove_if_stale(entry, cutoff))
                return removed
            except BaseException:
                # A replaced/invalid/unavailable root cannot leave an old root
                # cursor pinned indefinitely or be followed through a symlink.
                self._reset_cursor()
                raise

    def close(self):
        with self._guard:
            self._closed = True
            self._reset_cursor()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def cleanup_orphans(now=None):
    """One bounded cleanup pass; periodic owners should retain OrphanCleaner."""
    with OrphanCleaner() as cleaner:
        return cleaner.sweep(now)
