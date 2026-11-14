"""Opt-in, private local blob staging for FileShape 5.0.

This is NOT a distributed object store and is NOT connected to api.server,
JobRuntime or api.worker. Access methods take trusted, server-verified owner
and job identifiers; they MUST NOT be exposed as user-controlled API fields.

Bytes live only in private, regular filesystem files, never in SQLite job or
accounting records. SQLite holds opaque references, owners, digests and TTLs.
Publishing a candidate result is intentionally NOT implemented: that requires
atomic, lease-fenced approval in the durable dispatch ledger.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import threading
import time
from typing import Literal

from api.durable_jobs import DurableJobStore

REF_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_BLOB_BYTES = 45 * 1024 * 1024
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 1000
MAX_TTL = 24 * 3600


class BlobUnavailable(Exception):
    """Missing, expired, foreign or unsafe artifact (intentionally identical)."""


class BlobCapacity(Exception):
    """The bounded local store cannot admit more bytes or entries."""


def _valid_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 32
        and all(letter in REF_CHARS for letter in value)
    )


def _valid_owner(owner_id: object) -> bool:
    return type(owner_id) is int and 0 < owner_id <= 2**63 - 1


def _now(value: float | None) -> float:
    if value is None:
        value = time.time()
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Invalid timestamp")
    if not math.isfinite(value) or value <= 0 or value > 253402300799:
        raise ValueError("Invalid timestamp")
    return float(value)


def _ttl(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Invalid TTL")
    if not math.isfinite(value) or not 0 < value <= MAX_TTL:
        raise ValueError("Invalid TTL")
    return float(value)


class PrivateBlobStore:
    """Private local staging with owner/job scoping and short-lived artifacts.

    This storage cannot be replicated across hosts and has no network-facing
    operations. A future distributed service must preserve these invariants
    and add authenticated workers, durable output publication and deletion.
    """

    def __init__(
        self, root: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES, max_blob_bytes: int = MAX_BLOB_BYTES,
    ):
        if (
            type(max_bytes) is not int or max_bytes < 1
            or type(max_entries) is not int or not 1 <= max_entries <= 100000
            or type(max_blob_bytes) is not int or not 1 <= max_blob_bytes <= MAX_BLOB_BYTES
            or max_blob_bytes > max_bytes
        ):
            raise ValueError("Invalid storage limits")
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.max_blob_bytes = max_blob_bytes
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise RuntimeError("Blob directory must be private and service-owned")
        self._lock = threading.RLock()
        self._dir_fd = os.open(
            self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        self._db = None
        try:
            path = self.root / "blobs.sqlite3"
            DurableJobStore._prepare_file(path, create=True)
            for suffix in ("-wal", "-shm", "-journal"):
                DurableJobStore._prepare_file(
                    Path(str(path) + suffix), create=False,
                )
            db = sqlite3.connect(
                path, isolation_level=None, timeout=5, check_same_thread=False,
            )
            self._db = db
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("""
                CREATE TABLE IF NOT EXISTS staged_blobs (
                    ref TEXT PRIMARY KEY CHECK(length(ref)=32),
                    owner_id INTEGER NOT NULL CHECK(owner_id > 0),
                    job_id TEXT,
                    kind TEXT NOT NULL CHECK(kind IN ('input','candidate')),
                    byte_count INTEGER NOT NULL CHECK(byte_count > 0),
                    digest TEXT NOT NULL CHECK(length(digest)=64),
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    CHECK(kind='input' OR job_id IS NOT NULL)
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_staged_blobs_expiry "
                "ON staged_blobs(expires_at)"
            )
        except BaseException:
            if self._db is not None:
                self._db.close()
                self._db = None
            os.close(self._dir_fd)
            self._dir_fd = None
            raise

    def _open(self):
        if self._db is None or self._dir_fd is None:
            raise RuntimeError("Blob store is closed")
        return self._db

    def _write_private(self, ref: str, data: bytes) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
        fd = os.open(ref, flags, 0o600, dir_fd=self._dir_fd)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
            os.fsync(self._dir_fd)
        except BaseException:
            # Writing may fail after O_EXCL created the file; never leave
            # partially written private data behind on a caught error.
            try:
                os.unlink(ref, dir_fd=self._dir_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(fd)

    def _stage(
        self, owner_id: int, data: bytes, *, kind: Literal["input", "candidate"],
        job_id: str | None, ttl: float, now: float | None,
    ) -> str:
        if not _valid_owner(owner_id):
            raise ValueError("Invalid owner")
        if kind == "candidate" and not _valid_id(job_id):
            raise ValueError("Invalid job")
        if kind == "input" and job_id is not None:
            raise ValueError("Input must be unbound when staged")
        if type(data) is not bytes or not 0 < len(data) <= self.max_blob_bytes:
            raise ValueError("Invalid or oversized blob")
        timestamp = _now(now)
        expires = timestamp + _ttl(ttl)
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            db = self._open()
            db.execute("BEGIN IMMEDIATE")
            ref = None
            try:
                row = db.execute(
                    "SELECT COUNT(*), COALESCE(SUM(byte_count),0) FROM staged_blobs"
                ).fetchone()
                if (
                    row[0] >= self.max_entries
                    or row[1] + len(data) > self.max_bytes
                    or shutil.disk_usage(self.root).free < len(data) + 64 * 1024 * 1024
                ):
                    raise BlobCapacity()
                for _ in range(3):
                    candidate = secrets.token_urlsafe(24)
                    try:
                        self._write_private(candidate, data)
                    except FileExistsError:
                        continue
                    ref = candidate
                    break
                if ref is None:
                    raise BlobCapacity()
                db.execute(
                    """INSERT INTO staged_blobs
                       (ref,owner_id,job_id,kind,byte_count,digest,created_at,expires_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (ref, owner_id, job_id, kind, len(data), digest, timestamp, expires),
                )
                db.execute("COMMIT")
                return ref
            except BaseException:
                db.execute("ROLLBACK")
                if ref is not None:
                    os.unlink(ref, dir_fd=self._dir_fd)
                raise

    def stage_input(
        self, owner_id: int, data: bytes, *, ttl: float = 3600,
        now: float | None = None,
    ) -> str:
        """Stage verified-by-caller input; returns an opaque non-bearer ID."""
        if type(data) is not bytes or len(data) > MAX_INPUT_BYTES:
            raise ValueError("Input exceeds the existing 20 MiB upload limit")
        return self._stage(owner_id, data, kind="input", job_id=None, ttl=ttl, now=now)

    def stage_candidate(
        self, owner_id: int, job_id: str, data: bytes, *, ttl: float = 600,
        now: float | None = None,
    ) -> str:
        """Stage untrusted worker output; NEVER makes it downloadable."""
        return self._stage(
            owner_id, data, kind="candidate", job_id=job_id, ttl=ttl, now=now,
        )

    def bind_input(
        self, owner_id: int, job_id: str, ref: str, *, now: float | None = None,
    ) -> bool:
        """Bind staged input once to a trusted already-authorized job.

        This is not atomic with dispatch admission in another database.
        Only future trusted orchestration may call it after job authorization.
        """
        if not _valid_owner(owner_id) or not _valid_id(job_id) or not _valid_id(ref):
            raise BlobUnavailable()
        timestamp = _now(now)
        with self._lock:
            db = self._open()
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    """SELECT job_id FROM staged_blobs
                       WHERE ref=? AND owner_id=? AND kind='input'
                       AND expires_at>?""",
                    (ref, owner_id, timestamp),
                ).fetchone()
                if row is None or row[0] not in (None, job_id):
                    raise BlobUnavailable()
                if row[0] is None:
                    db.execute(
                        """UPDATE staged_blobs SET job_id=?
                           WHERE ref=? AND owner_id=? AND job_id IS NULL""",
                        (job_id, ref, owner_id),
                    )
                db.execute("COMMIT")
                return row[0] is None
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _read(
        self, owner_id: int, job_id: str, ref: str, kind: str,
        *, now: float | None,
    ) -> bytes:
        if not _valid_owner(owner_id) or not _valid_id(job_id) or not _valid_id(ref):
            raise BlobUnavailable()
        timestamp = _now(now)
        with self._lock:
            db = self._open()
            row = db.execute(
                """SELECT byte_count,digest FROM staged_blobs
                   WHERE ref=? AND owner_id=? AND job_id=? AND kind=?
                   AND expires_at>?""",
                (ref, owner_id, job_id, kind, timestamp),
            ).fetchone()
            if row is None:
                raise BlobUnavailable()
            fd = None
            try:
                fd = os.open(
                    ref, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=self._dir_fd,
                )
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_nlink != 1
                    or info.st_mode & 0o077
                    or info.st_size != row[0]
                    or not 0 < info.st_size <= self.max_blob_bytes
                ):
                    raise BlobUnavailable()
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(self.max_blob_bytes + 1)
                if (
                    len(data) != row[0]
                    or not secrets.compare_digest(
                        hashlib.sha256(data).hexdigest(), row[1],
                    )
                ):
                    raise BlobUnavailable()
                return data
            except OSError as exc:
                raise BlobUnavailable() from exc
            finally:
                if fd is not None:
                    os.close(fd)

    def read_input(
        self, owner_id: int, job_id: str, ref: str, *, now: float | None = None,
    ) -> bytes:
        """Read only a bound owner-scoped input (caller must authenticate owner)."""
        return self._read(owner_id, job_id, ref, "input", now=now)

    def read_candidate(
        self, owner_id: int, job_id: str, ref: str, *, now: float | None = None,
    ) -> bytes:
        """Internal verification only; a candidate is NOT a published output."""
        return self._read(owner_id, job_id, ref, "candidate", now=now)

    def delete(
        self, owner_id: int, ref: str, *, job_id: str | None = None,
    ) -> bool:
        """Owner-scoped deletion; missing/foreign refs are indistinguishable."""
        if not _valid_owner(owner_id) or not _valid_id(ref):
            raise BlobUnavailable()
        if job_id is not None and not _valid_id(job_id):
            raise BlobUnavailable()
        with self._lock:
            db = self._open()
            db.execute("BEGIN IMMEDIATE")
            try:
                if job_id is None:
                    changed = db.execute(
                        "DELETE FROM staged_blobs WHERE owner_id=? AND ref=?",
                        (owner_id, ref),
                    ).rowcount
                else:
                    changed = db.execute(
                        """DELETE FROM staged_blobs
                           WHERE owner_id=? AND ref=? AND job_id=?""",
                        (owner_id, ref, job_id),
                    ).rowcount
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            if changed:
                try:
                    os.unlink(ref, dir_fd=self._dir_fd)
                except FileNotFoundError:
                    pass
            return bool(changed)

    def purge_expired(self, *, now: float | None = None, limit: int = 100) -> int:
        """Delete expired entries and their files; must be run periodically."""
        timestamp = _now(now)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid purge batch")
        with self._lock:
            db = self._open()
            db.execute("BEGIN IMMEDIATE")
            try:
                refs = [
                    row[0] for row in db.execute(
                        """SELECT ref FROM staged_blobs WHERE expires_at<=?
                           ORDER BY expires_at,ref LIMIT ?""",
                        (timestamp, limit),
                    ).fetchall()
                ]
                for ref in refs:
                    db.execute("DELETE FROM staged_blobs WHERE ref=?", (ref,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            for ref in refs:
                try:
                    os.unlink(ref, dir_fd=self._dir_fd)
                except FileNotFoundError:
                    pass
            return len(refs)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                finally:
                    self._db = None
            if self._dir_fd is not None:
                os.close(self._dir_fd)
                self._dir_fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
