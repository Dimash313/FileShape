"""Bounded in-process waiting for conversion workers.

Waiting requests retain their HTTP connection; this is NOT a persistent job
queue. The asyncio semaphore supplies FIFO admission to available workers.
All state belongs to one API process and disappears on restart.
"""
import asyncio


class QueueFull(Exception):
    """The in-process waiting room has no free spaces."""


class QueueTimeout(Exception):
    """The request waited too long for a processing slot."""


class AdmissionQueue:
    def __init__(self, max_waiters: int = 20, wait_seconds: float = 90.0):
        if max_waiters < 0 or wait_seconds <= 0:
            raise ValueError("Invalid waiting-room settings")
        self.max_waiters = max_waiters
        self.wait_seconds = wait_seconds
        self.waiting = 0

    async def acquire(self, semaphore: asyncio.Semaphore) -> None:
        """Acquire one worker slot, or raise without leaking queue capacity.

        All calls run on a single asyncio event loop per API process. State
        changes before and after awaits are atomic within that loop.
        """
        queued = semaphore.locked()
        if queued:
            if self.waiting >= self.max_waiters:
                raise QueueFull()
            self.waiting += 1
        try:
            try:
                await asyncio.wait_for(semaphore.acquire(), self.wait_seconds)
            except asyncio.TimeoutError:
                raise QueueTimeout() from None
        finally:
            if queued:
                self.waiting -= 1
