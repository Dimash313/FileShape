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

from api.campaigns import CampaignMixin, initialize_campaign_tables
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


class DurableJobStore(CampaignMixin):
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
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS premium_entitlements (
                owner_id INTEGER PRIMARY KEY,
                expires_at REAL NOT NULL CHECK (expires_at > 0)
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS premium_grants (
                grant_key TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                seconds INTEGER NOT NULL CHECK (seconds > 0),
                granted_at REAL NOT NULL,
                resulting_expiry REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                chat_id INTEGER PRIMARY KEY,
                starts_at REAL NOT NULL,
                ends_at REAL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
                CHECK (ends_at IS NULL OR ends_at > starts_at)
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS owner_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_chat_id INTEGER NOT NULL,
                occurred_at REAL NOT NULL
            )
        """)
        initialize_campaign_tables(self._db)
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
    def create_idempotent(self, owner_id: int, key_hash: str, fingerprint: str, *, allow_create: bool = True) -> tuple[JobSnapshot, bool]:
        """Claim an owner-scoped operation without returning unvalidated IDs.

        An accepted duplicate returns its current metadata even at capacity.
        A pending duplicate never replaces the first upload's claim. Digests
        are validated before any storage access; raw keys/content stay outside
        this store. Rejected admissions must be removed with discard_queued.
        """
        self._validate_owner(owner_id)
        self._validate_admission_hash(key_hash)
        self._validate_admission_hash(fingerprint)
        if type(allow_create) is not bool:
            raise ValueError("Invalid admission creation setting")
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
                if not allow_create:
                    raise JobCapacityExceeded()
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

    @serialized
    def premium_expiry(self, owner_id: int) -> float | None:
        """Read durable UTC epoch expiry; no user files or payment secrets stored."""
        self._validate_owner(owner_id)
        row = self._db.execute(
            "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
            (owner_id,),
        ).fetchone()
        return None if row is None else float(row[0])

    @serialized
    def grant_premium(self, owner_id: int, seconds: int, grant_key: str, *,
                      now: float | None = None) -> tuple[float, bool]:
        """Atomically extend expiry; grant_key deduplicates payment/referral retries.

        This primitive does not verify payment, referral qualification or admin
        authorization. Only a trusted caller may supply an approved grant_key.
        """
        self._validate_owner(owner_id)
        if type(seconds) is not int or not 1 <= seconds <= 366 * 86400:
            raise ValueError("Invalid Premium duration")
        if not isinstance(grant_key, str) or re.fullmatch(r"[A-Za-z0-9:_-]{12,160}", grant_key) is None:
            raise ValueError("Invalid Premium grant key")
        if now is None:
            now = time.time()
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid grant timestamp")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                "SELECT owner_id,seconds,resulting_expiry FROM premium_grants WHERE grant_key=?",
                (grant_key,),
            ).fetchone()
            if existing is not None:
                if existing[0] != owner_id or existing[1] != seconds:
                    raise ValueError("Premium grant key conflict")
                expiry, created = float(existing[2]), False
            else:
                row = self._db.execute(
                    "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
                    (owner_id,),
                ).fetchone()
                base = max(float(now), float(row[0])) if row else float(now)
                expiry = base + seconds
                self._db.execute(
                    """INSERT INTO premium_entitlements(owner_id,expires_at) VALUES(?,?)
                       ON CONFLICT(owner_id) DO UPDATE SET expires_at=excluded.expires_at""",
                    (owner_id, expiry),
                )
                self._db.execute(
                    """INSERT INTO premium_grants(grant_key,owner_id,seconds,granted_at,resulting_expiry)
                       VALUES(?,?,?,?,?)""",
                    (grant_key, owner_id, seconds, now, expiry),
                )
                created = True
            self._db.execute("COMMIT")
            return expiry, created
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @staticmethod
    def _require_owner(actor_id: int, owner_id: int) -> None:
        """Both IDs must be trusted server configuration/authentication, not client claims."""
        DurableJobStore._validate_owner(actor_id)
        DurableJobStore._validate_owner(owner_id)
        if actor_id != owner_id:
            raise PermissionError("Owner authorization required")

    @serialized
    def set_required_channel(self, *, actor_id: int, owner_id: int, chat_id: int,
                             starts_at: float, ends_at: float | None = None,
                             enabled: bool = True, now: float | None = None) -> None:
        """Owner-only manual channel configuration. No automated partner approval."""
        self._require_owner(actor_id, owner_id)
        if type(chat_id) is not int or chat_id >= 0 or chat_id < -(2**63):
            raise ValueError("Invalid channel ID")
        if type(enabled) is not bool:
            raise ValueError("Invalid enabled flag")
        if not isinstance(starts_at, (int, float)) or not math.isfinite(starts_at) or starts_at <= 0:
            raise ValueError("Invalid channel start")
        if ends_at is not None and (
            not isinstance(ends_at, (int, float)) or not math.isfinite(ends_at) or ends_at <= starts_at
        ):
            raise ValueError("Invalid channel end")
        if now is None:
            now = time.time()
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid audit timestamp")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                """INSERT INTO required_channels(chat_id,starts_at,ends_at,enabled)
                   VALUES(?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                   starts_at=excluded.starts_at,ends_at=excluded.ends_at,enabled=excluded.enabled""",
                (chat_id, starts_at, ends_at, int(enabled)),
            )
            self._db.execute(
                "INSERT INTO owner_audit(actor_id,action,target_chat_id,occurred_at) VALUES(?,?,?,?)",
                (actor_id, "channel_upsert", chat_id, now),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @serialized
    def list_required_channels(self) -> list[tuple[int, float, float | None, bool]]:
        """Internal configuration; do not expose to unauthenticated clients."""
        rows = self._db.execute(
            "SELECT chat_id,starts_at,ends_at,enabled FROM required_channels ORDER BY chat_id"
        ).fetchall()
        return [(int(r[0]), float(r[1]), None if r[2] is None else float(r[2]), bool(r[3])) for r in rows]

    @serialized
    def remove_required_channel(self, *, actor_id: int, owner_id: int,
                                chat_id: int, now: float | None = None) -> bool:
        self._require_owner(actor_id, owner_id)
        if type(chat_id) is not int or chat_id >= 0 or chat_id < -(2**63):
            raise ValueError("Invalid channel ID")
        if now is None:
            now = time.time()
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid audit timestamp")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            removed = self._db.execute(
                "DELETE FROM required_channels WHERE chat_id=?", (chat_id,)
            ).rowcount == 1
            if removed:
                self._db.execute(
                    "INSERT INTO owner_audit(actor_id,action,target_chat_id,occurred_at) VALUES(?,?,?,?)",
                    (actor_id, "channel_remove", chat_id, now),
                )
            self._db.execute("COMMIT")
            return removed
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
