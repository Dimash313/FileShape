"""Bounded, shutdown-aware in-process admission for conversion workers.

The waiting room is not durable and does not survive process restarts.
Waiter notifications belong to each request's event loop.
"""
import asyncio


class QueueFull(Exception):
    """The waiting room has no free spaces."""


class QueueTimeout(Exception):
    """A request waited too long for a worker slot."""


class QueueClosed(Exception):
    """The server is shutting down and cannot accept more work."""


def _notify_waiter(waiter: asyncio.Future) -> None:
    if not waiter.done():
        waiter.set_result(None)


class AdmissionQueue:
    def __init__(self, max_waiters: int = 20, wait_seconds: float = 90.0):
        if max_waiters < 0 or wait_seconds <= 0:
            raise ValueError("Invalid waiting-room settings")
        self.max_waiters = max_waiters
        self.wait_seconds = wait_seconds
        self.waiting = 0
        self._closed = False
        self._shutdown_waiters: set[asyncio.Future] = set()

    def close(self) -> None:
        """Reject new work and wake existing requests on their own loops."""
        self._closed = True
        for waiter in tuple(self._shutdown_waiters):
            try:
                waiter.get_loop().call_soon_threadsafe(_notify_waiter, waiter)
            except RuntimeError:
                # The request's event loop has already exited.
                pass

    @property
    def closing(self) -> bool:
        return self._closed

    async def acquire(self, semaphore: asyncio.Semaphore) -> None:
        if self.closing:
            raise QueueClosed()
        # Claim an available permit before our first suspension point.
        # Scheduling all acquires in separate tasks would let a concurrent
        # burst observe the same free slot and bypass max_waiters.
        if not semaphore.locked():
            await semaphore.acquire()  # The unlocked fast path does not suspend.
            if self.closing:
                semaphore.release()
                raise QueueClosed()
            return
        queued = semaphore.locked()
        if queued:
            if self.waiting >= self.max_waiters:
                raise QueueFull()
            self.waiting += 1
        acquire_task = asyncio.create_task(semaphore.acquire())
        shutdown_notice = asyncio.get_running_loop().create_future()
        self._shutdown_waiters.add(shutdown_notice)
        acquired = False
        transferred = False
        try:
            done, _ = await asyncio.wait(
                (acquire_task, shutdown_notice),
                timeout=self.wait_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if acquire_task in done:
                acquired = acquire_task.result()
            if self.closing or shutdown_notice in done:
                raise QueueClosed()
            if acquire_task not in done:
                raise QueueTimeout()
            transferred = True
        finally:
            if not acquire_task.done():
                acquire_task.cancel()
            await asyncio.gather(acquire_task, return_exceptions=True)
            if not acquired and acquire_task.done() and not acquire_task.cancelled():
                try:
                    acquired = acquire_task.result() is True
                except Exception:
                    pass
            if acquired and not transferred:
                semaphore.release()
            self._shutdown_waiters.discard(shutdown_notice)
            if not shutdown_notice.done():
                shutdown_notice.cancel()
            if queued:
                self.waiting -= 1
