"""Bounded SQLite-backed job metadata used by server conversions.

Stores owner IDs, opaque job IDs and timestamps only. Never stores file paths,
names, uploaded bytes or results. Recovery marks interrupted jobs failed;
it cannot resume conversions without a durable, privacy-safe file pipeline.
"""
import os
import secrets
import sqlite3
import stat
import time
import math
import threading
from functools import wraps
from pathlib import Path

from api.jobs import JobCapacityExceeded, JobNotFound, JobSnapshot, JobStateError, TRANSITIONS


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class DurableJobStore:
    def __init__(self, path: str | Path, *, max_entries: int = 1000, retention_seconds: float = 3600):
        if type(max_entries) is not int or max_entries < 1 or not math.isfinite(retention_seconds) or retention_seconds <= 0:
            raise ValueError("Invalid store settings")
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self._lock = threading.RLock()
        self.path = str(path)
        # The parent directory must be private and service-owned. SQLite opens
        # sidecars by pathname; untrusted directory writers cannot be supported.
        if self.path != ":memory:":
            self._prepare_file(Path(self.path), create=True)
            for suffix in ("-wal", "-shm", "-journal"):
                self._prepare_file(Path(self.path + suffix), create=False)
        self._db = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        try:
            self._initialize()
        except BaseException:
            self._db.close()
            raise

    @staticmethod
    def _prepare_file(path: Path, *, create: bool) -> None:
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        if create:
            flags |= os.O_CREAT
        if path.is_symlink():
            raise ValueError("Job database files must not be symlinks")
        try:
            fd = os.open(path, flags, 0o600)
        except FileNotFoundError:
            if not create:
                return
            raise
        except OSError as exc:
            raise ValueError("Unsafe job database file") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Job database files must be regular files with one link")
            if os.name == "posix":
                if info.st_uid != os.geteuid():
                    raise ValueError("Job database files must be service-owned")
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    def _initialize(self) -> None:
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_id)")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state_updated ON jobs(state, updated_at)")

    @serialized
    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _snapshot(row) -> JobSnapshot:
        return JobSnapshot(row[0], row[1], row[2], row[3])

    @serialized
    def create(self, owner_id: int) -> JobSnapshot:
        if type(owner_id) is not int or not 0 < owner_id <= 2**63 - 1:
            raise ValueError("Invalid owner")
        now = time.time()
        job_id = secrets.token_urlsafe(24)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self.prune_terminal(self.retention_seconds)
            if self._db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= self.max_entries:
                raise JobCapacityExceeded()
            self._db.execute(
                "INSERT INTO jobs(job_id,owner_id,state,created_at,updated_at) VALUES(?,?,?,?,?)",
                (job_id, owner_id, "queued", now, now),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return JobSnapshot(job_id, "queued", now, now)

    @serialized
    def get(self, job_id: str, owner_id: int) -> JobSnapshot:
        self.prune_terminal(self.retention_seconds)
        if type(owner_id) is not int or not 0 < owner_id <= 2**63 - 1:
            raise JobNotFound()
        row = self._db.execute(
            "SELECT job_id,state,created_at,updated_at FROM jobs WHERE job_id=? AND owner_id=?",
            (job_id, owner_id),
        ).fetchone()
        if row is None:
            raise JobNotFound()
        return self._snapshot(row)

    @serialized
    def transition(self, job_id: str, owner_id: int, state: str) -> JobSnapshot:
        item = self.get(job_id, owner_id)
        if state not in TRANSITIONS[item.state]:
            raise JobStateError()
        now = time.time()
        changed = self._db.execute(
            "UPDATE jobs SET state=?,updated_at=? WHERE job_id=? AND owner_id=? AND state=?",
            (state, now, job_id, owner_id, item.state),
        ).rowcount
        if changed != 1:
            raise JobStateError()
        return JobSnapshot(job_id, state, item.created_at, now)

    @serialized
    def discard_queued(self, job_id: str, owner_id: int) -> bool:
        """Remove an admission that was never accepted/returned to a caller.

        Callers must not use this for admitted jobs. The owner/state predicates
        also prevent deleting another owner's or an already running record.
        """
        if type(owner_id) is not int or not 0 < owner_id <= 2**63 - 1:
            raise JobNotFound()
        return self._db.execute(
            "DELETE FROM jobs WHERE job_id=? AND owner_id=? AND state='queued'",
            (job_id, owner_id),
        ).rowcount == 1

    @serialized
    def mark_interrupted_failed(self) -> int:
        """Run only when all workers are stopped; does not replay any work."""
        return self._db.execute(
            "UPDATE jobs SET state='failed',updated_at=? WHERE state IN ('queued','processing')",
            (time.time(),),
        ).rowcount

    @serialized
    def prune_terminal(self, retention_seconds: float = 3600) -> int:
        if not math.isfinite(retention_seconds) or retention_seconds <= 0:
            raise ValueError("Invalid retention")
        return self._db.execute(
            "DELETE FROM jobs WHERE state IN ('completed','failed','cancelled') AND updated_at<=?",
            (time.time() - retention_seconds,),
        ).rowcount
