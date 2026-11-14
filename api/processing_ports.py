"""Stable logical interfaces for single-file job processing.

These are *contracts*, not distributed implementations. They describe the
existing atomic metadata store, bounded dispatcher and private artifact store.
Replacing any implementation requires behavioral parity, owner isolation,
reconciliation and crash/duplicate-delivery tests.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from api.jobs import JobSnapshot


@runtime_checkable
class JobMetadataPort(Protocol):
    """Owner-scoped metadata; terminal transitions settle quota atomically."""

    max_entries: int

    def create(self, owner_id: int, *, metered: bool = False) -> JobSnapshot: ...

    def create_idempotent(
        self, owner_id: int, key_hash: str, fingerprint: str,
        *, allow_create: bool = True, metered: bool = False,
    ) -> tuple[JobSnapshot, bool]: ...

    def accept_admission(self, job_id: str, owner_id: int, key_hash: str) -> None: ...

    def discard_queued(self, job_id: str, owner_id: int) -> bool: ...

    def get(self, job_id: str, owner_id: int) -> JobSnapshot: ...

    def transition(self, job_id: str, owner_id: int, state: str) -> JobSnapshot: ...


@runtime_checkable
class JobHandlePort(Protocol):
    """Completion is distinct from cancellation and resource cleanup."""

    @property
    def result(self) -> asyncio.Future[Any]: ...

    @property
    def finished(self) -> asyncio.Future[None]: ...

    @property
    def done(self) -> bool: ...

    async def cancel(self) -> None: ...


@runtime_checkable
class DispatcherPort(Protocol):
    """Bounded admission; overload must never silently drop admitted work."""

    capacity: int

    def submit(self, operation: Callable[[], Awaitable[Any]]) -> JobHandlePort: ...

    async def run(self, operation: Callable[[], Awaitable[Any]]) -> Any: ...

    async def close(self) -> None: ...


@runtime_checkable
class ArtifactReservationPort(Protocol):
    """Private workspace, only valid for this reservation's lifecycle."""

    path: Path


@runtime_checkable
class ResultLeasePort(Protocol):
    """An open download lease keeps artifact bytes reserved until closed."""

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class ArtifactPort(Protocol):
    """Temporary, bounded artifacts; separate owner authorization is mandatory."""

    def reserve(self, job_id: str, reservation_bytes: int) -> ArtifactReservationPort: ...

    def complete(self, job_id: str, filename: str, content_type: str) -> None: ...

    def discard(self, job_id: str) -> None: ...

    def discard_unfinished(self, job_id: str) -> bool: ...

    def open_result(self, job_id: str) -> tuple[ResultLeasePort, int, str, str]: ...

    def reconcile(self) -> int: ...

    def close(self) -> None: ...


WorkerPort = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
