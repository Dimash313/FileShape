"""Bounded in-process dispatch. Durable metadata and file ownership stay with callers.

Operations must cooperate with cancellation; production operations use the
resource-limited subprocess runner, which kills/reaps its process group.
"""
import asyncio
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any


class ManagerClosed(Exception):
    pass


class ManagerFull(Exception):
    pass


@dataclass(eq=False)
class _Ticket:
    operation: Callable[[], Awaitable[Any]]
    result: asyncio.Future
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    cancellation_requested: bool = False


class JobManager:
    def __init__(self, capacity: int, max_pending: int = 20, timeout: float = 50):
        if type(capacity) is not int or not 1 <= capacity <= 10 or type(max_pending) is not int or not 1 <= max_pending <= 1000 or not 0 < timeout <= 120:
            raise ValueError("Invalid job manager settings")
        self.capacity = capacity
        self.timeout = timeout
        self._queue = asyncio.Queue(maxsize=max_pending)
        self._active: set[_Ticket] = set()
        self._closed = False
        self._workers = [asyncio.create_task(self._consume()) for _ in range(capacity)]
        self._shutdown = None

    @property
    def waiting(self):
        return self._queue.qsize()

    @property
    def active(self):
        return len(self._active)

    @staticmethod
    def _cancel(ticket):
        if ticket.cancellation_requested:
            return
        ticket.cancellation_requested = True
        ticket.result.cancel()
        if ticket.task is not None:
            ticket.task.cancel()
        else:
            ticket.finished.set()

    async def run(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        if self._closed:
            raise ManagerClosed()
        ticket = _Ticket(operation, asyncio.get_running_loop().create_future())
        try:
            self._queue.put_nowait(ticket)
        except asyncio.QueueFull:
            raise ManagerFull() from None
        try:
            return await asyncio.shield(ticket.result)
        except asyncio.CancelledError:
            self._cancel(ticket)
            # Do not let caller cleanup remove files under a live subprocess.
            cleanup = asyncio.create_task(ticket.finished.wait())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    # A repeated caller cancellation must not race file cleanup.
                    continue
            raise

    async def _consume(self):
        while True:
            ticket = await self._queue.get()
            if ticket is None:
                self._queue.task_done()
                return
            try:
                if ticket.result.cancelled():
                    continue
                self._active.add(ticket)
                ticket.task = asyncio.create_task(ticket.operation())
                result = await asyncio.wait_for(ticket.task, self.timeout)
                if not ticket.result.done():
                    ticket.result.set_result(result)
            except asyncio.CancelledError:
                ticket.result.cancel()
            except Exception as exc:
                if not ticket.result.done():
                    # Do not expose this live consumer frame through the future.
                    # Traceback-clearing callers must not close the consumer.
                    ticket.result.set_exception(exc.with_traceback(None))
            finally:
                self._active.discard(ticket)
                ticket.finished.set()
                self._queue.task_done()

    async def close(self):
        # One shared shutdown task makes repeated/concurrent close idempotent.
        if self._shutdown is None:
            self._closed = True
            self._shutdown = asyncio.create_task(self._stop())
        await asyncio.shield(self._shutdown)

    async def _stop(self):
        while True:
            try:
                ticket = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._cancel(ticket)
            self._queue.task_done()
        for ticket in tuple(self._active):
            self._cancel(ticket)
        # Reaping active subprocesses completes before workers exit.
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers)
