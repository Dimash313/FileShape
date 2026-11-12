"""Dispatch limits, error isolation, cancellation ordering and shutdown."""
import asyncio
import unittest

from api.job_manager import JobManager, ManagerClosed, ManagerFull


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class JobManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallelism_queue_capacity_and_overload(self):
        manager = JobManager(2, max_pending=1)
        self.addAsyncCleanup(manager.close)
        release = asyncio.Event()
        active = 0
        peak = 0
        async def operation():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await release.wait()
                return 42
            finally:
                active -= 1
        first = asyncio.create_task(manager.run(operation))
        await wait_until(lambda: manager.active == 1)
        second = asyncio.create_task(manager.run(operation))
        await wait_until(lambda: manager.active == 2)
        queued = asyncio.create_task(manager.run(operation))
        await wait_until(lambda: manager.waiting == 1)
        with self.assertRaises(ManagerFull):
            await manager.run(operation)
        release.set()
        self.assertEqual(await asyncio.gather(first, second, queued), [42, 42, 42])
        self.assertEqual(peak, 2)

    async def test_operation_error_does_not_kill_consumer(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        async def fail():
            raise ValueError("operation failed")
        async def succeed():
            return "next"
        with self.assertRaises(ValueError):
            await manager.run(fail)
        self.assertEqual(await manager.run(succeed), "next")
        self.assertEqual(manager.active, 0)

    async def test_invalid_operation_is_reported_without_losing_worker(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        with self.assertRaises(TypeError):
            await manager.run(lambda: 1)
        self.assertEqual(await manager.run(lambda: asyncio.sleep(0, result=2)), 2)

    async def test_running_cancel_waits_for_operation_cleanup(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        entered = asyncio.Event()
        cleanup_entered = asyncio.Event()
        allow_cleanup = asyncio.Event()
        async def operation():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_entered.set()
                await allow_cleanup.wait()
        caller = asyncio.create_task(manager.run(operation))
        await entered.wait()
        caller.cancel()
        await cleanup_entered.wait()
        self.assertFalse(caller.done())
        caller.cancel()
        await asyncio.sleep(0)
        self.assertFalse(caller.done())
        self.assertEqual(manager.active, 1)
        allow_cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(manager.active, 0)

    async def test_pending_cancel_never_starts_operation(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        release = asyncio.Event()
        first = asyncio.create_task(manager.run(release.wait))
        await wait_until(lambda: manager.active == 1)
        calls = []
        async def pending():
            calls.append(True)
        second = asyncio.create_task(manager.run(pending))
        await wait_until(lambda: manager.waiting == 1)
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second
        release.set()
        await first
        await wait_until(lambda: manager.waiting == 0)
        self.assertEqual(calls, [])

    async def test_shutdown_cancels_waiters_and_joins_cleanup(self):
        manager = JobManager(1)
        cleaned = asyncio.Event()
        async def operation():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        first = asyncio.create_task(manager.run(operation))
        await wait_until(lambda: manager.active == 1)
        second = asyncio.create_task(manager.run(operation))
        await wait_until(lambda: manager.waiting == 1)
        await asyncio.wait_for(asyncio.gather(manager.close(), manager.close()), 3)
        self.assertTrue(cleaned.is_set())
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes))
        self.assertEqual(manager.active, 0)
        self.assertEqual(manager.waiting, 0)
        self.assertTrue(all(worker.done() for worker in manager._workers))
        with self.assertRaises(ManagerClosed):
            await manager.run(operation)

    async def test_timeout_cleans_up_and_consumer_continues(self):
        manager = JobManager(1, timeout=0.02)
        self.addAsyncCleanup(manager.close)
        cleaned = asyncio.Event()
        async def operation():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        with self.assertRaises(TimeoutError):
            await manager.run(operation)
        self.assertTrue(cleaned.is_set())
        self.assertEqual(await manager.run(lambda: asyncio.sleep(0, result=7)), 7)
