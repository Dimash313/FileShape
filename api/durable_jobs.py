"""SQLite-backed job *metadata* prototype; not connected to conversion routes.

Stores owner IDs, opaque job IDs and timestamps only. Never stores file paths,
names, uploaded bytes or results. Recovery marks interrupted jobs failed;
it cannot resume conversions without a durable, privacy-safe file pipeline.
"""
import secrets
import sqlite3
import time
from pathlib import Path

from api.jobs import JobNotFound, JobSnapshot, JobStateError, TRANSITIONS


class DurableJobStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA journal_mode=WAL")
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

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _snapshot(row) -> JobSnapshot:
        return JobSnapshot(row[0], row[1], row[2], row[3])

    def create(self, owner_id: int) -> JobSnapshot:
        if type(owner_id) is not int or owner_id <= 0:
            raise ValueError("Invalid owner")
        now = time.time()
        job_id = secrets.token_urlsafe(24)
        self._db.execute(
            "INSERT INTO jobs(job_id,owner_id,state,created_at,updated_at) VALUES(?,?,?,?,?)",
            (job_id, owner_id, "queued", now, now),
        )
        return JobSnapshot(job_id, "queued", now, now)

    def get(self, job_id: str, owner_id: int) -> JobSnapshot:
        if type(owner_id) is not int:
            raise JobNotFound()
        row = self._db.execute(
            "SELECT job_id,state,created_at,updated_at FROM jobs WHERE job_id=? AND owner_id=?",
            (job_id, owner_id),
        ).fetchone()
        if row is None:
            raise JobNotFound()
        return self._snapshot(row)

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

    def mark_interrupted_failed(self) -> int:
        """Run only when all workers are stopped; does not replay any work."""
        return self._db.execute(
            "UPDATE jobs SET state='failed',updated_at=? WHERE state IN ('queued','processing')",
            (time.time(),),
        ).rowcount

    def prune_terminal(self, retention_seconds: float = 3600) -> int:
        if retention_seconds <= 0:
            raise ValueError("Invalid retention")
        return self._db.execute(
            "DELETE FROM jobs WHERE state IN ('completed','failed','cancelled') AND updated_at<=?",
            (time.time() - retention_seconds,),
        ).rowcount
