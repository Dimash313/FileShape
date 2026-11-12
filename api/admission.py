"""Bounded, shutdown-aware in-process admission for conversion workers.

The waiting room is not durable and does not survive process restarts.
"""
import asyncio


class QueueFull(Exception):
    """The waiting room has no free spaces."""


class QueueTimeout(Exception):
    """A request waited too long for a worker slot."""


class QueueClosed(Exception):
    """The server is shutting down and cannot accept more work."""


class AdmissionQueue:
    def __init__(self, max_waiters: int = 20, wait_seconds: float = 90.0):
        if max_waiters < 0 or wait_seconds <= 0:
            raise ValueError("Invalid waiting-room settings")
        self.max_waiters = max_waiters
        self.wait_seconds = wait_seconds
        self.waiting = 0
        self._closing = asyncio.Event()

    def close(self) -> None:
        """Reject new admissions and wake waiting requests promptly."""
        self._closing.set()

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    async def acquire(self, semaphore: asyncio.Semaphore) -> None:
        if self.closing:
            raise QueueClosed()
        queued = semaphore.locked()
        if queued:
            if self.waiting >= self.max_waiters:
                raise QueueFull()
            self.waiting += 1
        acquire_task = asyncio.create_task(semaphore.acquire())
        closing_task = asyncio.create_task(self._closing.wait())
        acquired = False
        transferred = False
        try:
            done, _ = await asyncio.wait(
                (acquire_task, closing_task),
                timeout=self.wait_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if acquire_task in done:
                acquired = acquire_task.result()
            if self.closing or closing_task in done:
                raise QueueClosed()
            if acquire_task not in done:
                raise QueueTimeout()
            # The caller owns the slot after successful return.
            transferred = True
        finally:
            # On cancellation, timeout or shutdown the semaphore permit must
            # never leak, including a simultaneous close/acquire race.
            for task in (acquire_task, closing_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(acquire_task, closing_task, return_exceptions=True)
            if not acquired and acquire_task.done() and not acquire_task.cancelled():
                try:
                    acquired = acquire_task.result() is True
                except Exception:
                    pass
            if acquired and not transferred:
                semaphore.release()
            if queued:
                self.waiting -= 1
