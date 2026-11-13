"""Bounded SQLite-backed job metadata used by server conversions.

Stores owner IDs, opaque job IDs, states, timestamps and admission digests.
Never stores raw idempotency keys, file paths, names, uploaded bytes or results. Recovery marks interrupted jobs failed;
it cannot resume conversions without a durable, privacy-safe file pipeline.
"""
import os
import re
import secrets
import sqlite3
import stat
import time
import math
import threading
from functools import wraps
from pathlib import Path

from api.jobs import JobCapacityExceeded, JobNotFound, JobSnapshot, JobStateError, TRANSITIONS


_ADMISSION_HASH = re.compile(r"[0-9a-f]{64}\Z")


class IdempotencyConflict(Exception):
    """The owner already claimed this key for a different operation."""


class IdempotencyPending(Exception):
    """The matching operation has not completed upload validation/admission."""


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
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS admissions (
                owner_id INTEGER NOT NULL,
                key_hash TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id) ON DELETE CASCADE,
                accepted INTEGER NOT NULL DEFAULT 0 CHECK (accepted IN (0, 1)),
                created_at REAL NOT NULL,
                PRIMARY KEY (owner_id, key_hash)
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

    @staticmethod
    def _validate_owner(owner_id: int) -> None:
        if type(owner_id) is not int or not 0 < owner_id <= 2**63 - 1:
            raise ValueError("Invalid owner")

    @staticmethod
    def _validate_admission_hash(value: str) -> None:
        if not isinstance(value, str) or _ADMISSION_HASH.fullmatch(value) is None:
            raise ValueError("Invalid admission hash")

    def _insert_queued(self, owner_id: int, now: float) -> JobSnapshot:
        """Caller holds the connection lock and a write transaction."""
        if self._db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= self.max_entries:
            raise JobCapacityExceeded()
        job_id = secrets.token_urlsafe(24)
        self._db.execute(
            "INSERT INTO jobs(job_id,owner_id,state,created_at,updated_at) VALUES(?,?,?,?,?)",
            (job_id, owner_id, "queued", now, now),
        )
        return JobSnapshot(job_id, "queued", now, now)

    @serialized
    def create(self, owner_id: int) -> JobSnapshot:
        self._validate_owner(owner_id)
        now = time.time()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self.prune_terminal(self.retention_seconds)
            job = self._insert_queued(owner_id, now)
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return job

    @serialized
    def create_idempotent(self, owner_id: int, key_hash: str, fingerprint: str) -> tuple[JobSnapshot, bool]:
        """Claim an owner-scoped operation without returning unvalidated IDs.

        An accepted duplicate returns its current metadata even at capacity.
        A pending duplicate never replaces the first upload's claim. Digests
        are validated before any storage access; raw keys/content stay outside
        this store. Rejected admissions must be removed with discard_queued.
        """
        self._validate_owner(owner_id)
        self._validate_admission_hash(key_hash)
        self._validate_admission_hash(fingerprint)
        now = time.time()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self.prune_terminal(self.retention_seconds)
            existing = self._db.execute(
                """SELECT a.fingerprint,a.accepted,j.job_id,j.state,j.created_at,j.updated_at
                   FROM admissions AS a JOIN jobs AS j ON j.job_id=a.job_id
                   WHERE a.owner_id=? AND a.key_hash=? AND j.owner_id=?""",
                (owner_id, key_hash, owner_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise IdempotencyConflict()
                if not existing[1]:
                    raise IdempotencyPending()
                job = self._snapshot(existing[2:])
                is_new = False
            else:
                job = self._insert_queued(owner_id, now)
                self._db.execute(
                    """INSERT INTO admissions(owner_id,key_hash,fingerprint,job_id,accepted,created_at)
                       VALUES(?,?,?,?,0,?)""",
                    (owner_id, key_hash, fingerprint, job.job_id, now),
                )
                is_new = True
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return job, is_new

    @serialized
    def accept_admission(self, job_id: str, owner_id: int, key_hash: str) -> None:
        """Publish only a mapping belonging to this owner, key and job."""
        if type(owner_id) is not int or not 0 < owner_id <= 2**63 - 1:
            raise JobNotFound()
        self._validate_admission_hash(key_hash)
        changed = self._db.execute(
            """UPDATE admissions SET accepted=1
               WHERE job_id=? AND owner_id=? AND key_hash=?
                 AND EXISTS(SELECT 1 FROM jobs WHERE job_id=? AND owner_id=?)""",
            (job_id, owner_id, key_hash, job_id, owner_id),
        ).rowcount
        if changed != 1:
            raise JobNotFound()

    @serialized
    def discard_pending_admissions(self) -> int:
        """After exclusive startup ownership, remove never-accepted uploads.

        No caller received these operation IDs; they must not become replayable
        accepted jobs merely because an API process restarted during validation.
        """
        return self._db.execute(
            "DELETE FROM jobs WHERE job_id IN (SELECT job_id FROM admissions WHERE accepted=0)"
        ).rowcount

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
