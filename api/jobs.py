"""Privacy-minimal, bounded in-memory job metadata foundation.

This registry deliberately stores no filenames, file contents or user profiles.
It is not durable, shared between processes, or a background job queue.
"""
from dataclasses import dataclass
import secrets
import time


TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
TRANSITIONS = {
    "queued": frozenset({"processing", "failed", "cancelled"}),
    "processing": TERMINAL_STATES,
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class JobNotFound(Exception):
    pass


class JobStateError(Exception):
    pass


class JobCapacityExceeded(Exception):
    pass


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    state: str
    created_at: float
    updated_at: float

    def public(self) -> dict:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "created_at": int(self.created_at),
            "updated_at": int(self.updated_at),
        }


class JobRegistry:
    def __init__(self, *, max_entries: int = 1000, retention_seconds: float = 3600):
        if max_entries < 1 or retention_seconds <= 0:
            raise ValueError("Invalid registry settings")
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self._jobs: dict[str, tuple[int, JobSnapshot]] = {}

    def _prune(self, now: float) -> None:
        for key, (_, item) in tuple(self._jobs.items()):
            if item.state in TERMINAL_STATES and now - item.updated_at >= self.retention_seconds:
                del self._jobs[key]

    def create(self, user_id: int) -> JobSnapshot:
        if type(user_id) is not int or user_id <= 0:
            raise ValueError("Invalid owner")
        now = time.time()
        self._prune(now)
        if len(self._jobs) >= self.max_entries:
            # Never silently evict active jobs.
            raise JobCapacityExceeded()
        while True:
            job_id = secrets.token_urlsafe(24)
            if job_id not in self._jobs:
                break
        item = JobSnapshot(job_id, "queued", now, now)
        self._jobs[job_id] = (user_id, item)
        return item

    def get(self, job_id: str, user_id: int) -> JobSnapshot:
        self._prune(time.time())
        stored = self._jobs.get(job_id)
        # Missing and other users' jobs are intentionally indistinguishable.
        if not stored or type(user_id) is not int or stored[0] != user_id:
            raise JobNotFound()
        return stored[1]

    def transition(self, job_id: str, user_id: int, state: str) -> JobSnapshot:
        item = self.get(job_id, user_id)
        if state not in TRANSITIONS[item.state]:
            raise JobStateError()
        updated = JobSnapshot(job_id, state, item.created_at, time.time())
        self._jobs[job_id] = (user_id, updated)
        return updated

    def clear(self) -> None:
        """Drop all metadata at process shutdown; do not pretend to persist."""
        self._jobs.clear()
