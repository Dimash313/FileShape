"""Bounded in-process dispatch. Durable metadata and file ownership stay with callers.

Operations must cooperate with cancellation; production operations use the
resource-limited subprocess runner, which kills/reaps its process group.
"""
import asyncio
from dataclasses import dataclass
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
    finished: asyncio.Future
    task: asyncio.Task | None = None
    cancellation_requested: bool = False


class JobHandle:
    """One admitted operation; result completion and cleanup are distinct.

    Use cancel() to cancel and wait for resource cleanup. The finished future
    resolves only after cleanup (or before execution for queued cancellation).
    Result exceptions are observed even if no HTTP caller waits for them.
    """
    def __init__(self, manager, ticket):
        self._manager = manager
        self._ticket = ticket

    @property
    def result(self) -> asyncio.Future:
        return self._ticket.result

    @property
    def finished(self) -> asyncio.Future:
        # A callback/awaiter cannot cancel the manager's cleanup notification.
        return asyncio.shield(self._ticket.finished)

    @property
    def done(self) -> bool:
        return self._ticket.finished.done()

    async def cancel(self) -> None:
        self._manager._cancel(self._ticket)
        interrupted = False
        while not self._ticket.finished.done():
            try:
                await asyncio.shield(self._ticket.finished)
            except asyncio.CancelledError:
                # Repeated caller cancellation must not race file cleanup.
                interrupted = True
        if interrupted:
            raise asyncio.CancelledError()

    async def wait(self) -> Any:
        try:
            return await asyncio.shield(self.result)
        except asyncio.CancelledError:
            await self.cancel()
            raise


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
            JobManager._finish(ticket)

    @staticmethod
    def _finish(ticket):
        if not ticket.finished.done():
            ticket.finished.set_result(None)

    def _observe_result(self, ticket, result):
        if result.cancelled():
            self._cancel(ticket)
        else:
            # Retrieve failures for fire-and-forget submissions. Awaiting the
            # same future still raises its original operation exception.
            result.exception()

    def submit(self, operation: Callable[[], Awaitable[Any]]) -> JobHandle:
        """Admit synchronously; only fixed consumers start operation tasks."""
        if self._closed:
            raise ManagerClosed()
        loop = asyncio.get_running_loop()
        ticket = _Ticket(operation, loop.create_future(), loop.create_future())
        try:
            self._queue.put_nowait(ticket)
        except asyncio.QueueFull:
            raise ManagerFull() from None
        ticket.result.add_done_callback(lambda result: self._observe_result(ticket, result))
        return JobHandle(self, ticket)

    async def run(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        return await self.submit(operation).wait()

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
                JobManager._finish(ticket)
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
