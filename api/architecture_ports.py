"""Structural contracts for FileShape's current background job pipeline.

These ports make dependencies explicit without replacing the existing secure
single-process implementations. A future PostgreSQL/queue/object-store adapter
must satisfy the *behavioral* guarantees too, not just these method names.

IMPORTANT: a submitted operation is currently an in-process Python closure.
The dispatcher port is NOT a distributed queue and must not be treated as one.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from api.jobs import JobSnapshot


@runtime_checkable
class JobMetadataPort(Protocol):
    """Owner-scoped metadata with atomic metering on create/transition/discard."""

    max_entries: int

    def create(self, owner_id: int, *, metered: bool = False) -> JobSnapshot: ...

    def create_idempotent(
        self, owner_id: int, key_hash: str, fingerprint: str,
        *, allow_create: bool = True, metered: bool = False,
    ) -> tuple[JobSnapshot, bool]: ...

    def accept_admission(self, job_id: str, owner_id: int, key_hash: str) -> None: ...

    def get(self, job_id: str, owner_id: int) -> JobSnapshot: ...

    def transition(self, job_id: str, owner_id: int, state: str) -> JobSnapshot: ...

    def discard_queued(self, job_id: str, owner_id: int) -> bool: ...


@runtime_checkable
class DispatchHandlePort(Protocol):
    """A handle remains alive until execution and cleanup have finished."""

    @property
    def result(self) -> asyncio.Future[Any]: ...

    @property
    def finished(self) -> asyncio.Future[Any]: ...

    @property
    def done(self) -> bool: ...

    async def cancel(self) -> None: ...


@runtime_checkable
class JobDispatchPort(Protocol):
    """Bounded in-process dispatch; replacing it needs a new serializable API."""

    capacity: int

    def submit(self, operation: Callable[[], Awaitable[Any]]) -> DispatchHandlePort: ...

    async def run(self, operation: Callable[[], Awaitable[Any]]) -> Any: ...

    async def close(self) -> None: ...


@runtime_checkable
class ArtifactReservationPort(Protocol):
    """Local private workspace allocated to one accepted job."""

    path: Path


@runtime_checkable
class ArtifactStoragePort(Protocol):
    """Ephemeral result lifecycle; caller authorizes retrieval separately."""

    def reserve(self, job_id: str, reservation_bytes: int) -> ArtifactReservationPort: ...

    def complete(self, job_id: str, filename: str, content_type: str) -> None: ...

    def discard(self, job_id: str) -> None: ...

    def discard_unfinished(self, job_id: str) -> None: ...

    def close(self) -> None: ...
