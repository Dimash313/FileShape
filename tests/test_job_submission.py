"""Synchronous bounded submission and background completion contracts."""
import asyncio
import gc
import unittest

from api.job_manager import JobManager, ManagerClosed, ManagerFull


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class JobSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_returns_before_execution_and_enforces_queue_limit(self):
        manager = JobManager(1, max_pending=2)
        self.addAsyncCleanup(manager.close)
        entered = []
        async def operation():
            entered.append(True)
            return "ready"
        first = manager.submit(operation)
        second = manager.submit(operation)
        self.assertEqual(entered, [])
        self.assertFalse(first.done)
        self.assertFalse(first.result.done())
        with self.assertRaises(ManagerFull):
            manager.submit(operation)
        self.assertEqual(await first.wait(), "ready")
        self.assertEqual(await second.wait(), "ready")
        self.assertTrue(first.done)
        await manager.close()
        with self.assertRaises(ManagerClosed):
            manager.submit(operation)

    async def test_queued_handle_cancel_never_starts_operation(self):
        manager = JobManager(1, max_pending=2)
        self.addAsyncCleanup(manager.close)
        release = asyncio.Event()
        first = manager.submit(release.wait)
        await wait_until(lambda: manager.active == 1)
        executed = []
        async def pending():
            executed.append(True)
        queued = manager.submit(pending)
        await queued.cancel()
        self.assertTrue(queued.done)
        self.assertTrue(queued.result.cancelled())
        await queued.finished
        release.set()
        await first.wait()
        await wait_until(lambda: manager.waiting == 0)
        self.assertEqual(executed, [])

    async def test_running_handle_cancel_waits_even_when_cancel_caller_cancelled(self):
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
        handle = manager.submit(operation)
        await entered.wait()
        cancelling = asyncio.create_task(handle.cancel())
        await cleanup_entered.wait()
        cancelling.cancel()
        await asyncio.sleep(0)
        self.assertFalse(cancelling.done())
        self.assertFalse(handle.done)
        self.assertFalse(handle.finished.done())
        allow_cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await cancelling
        self.assertTrue(handle.done)
        self.assertEqual(manager.active, 0)

    async def test_background_error_is_observed_and_consumer_survives(self):
        loop = asyncio.get_running_loop()
        reports = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda current_loop, context: reports.append(context))
        self.addCleanup(loop.set_exception_handler, previous)
        manager = JobManager(1)
        async def fail():
            raise ValueError("background failure")
        handle = manager.submit(fail)
        await handle.finished
        # No waiter retrieves this result; dispatch must still consume errors.
        del handle
        await manager.run(lambda: asyncio.sleep(0, result="next"))
        await manager.close()
        gc.collect()
        await asyncio.sleep(0)
        self.assertEqual(reports, [])

    async def test_observed_background_error_still_reaches_waiter(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        async def fail():
            raise ValueError("reported")
        handle = manager.submit(fail)
        await handle.finished
        with self.assertRaisesRegex(ValueError, "reported"):
            await handle.wait()
        self.assertEqual(await manager.run(lambda: asyncio.sleep(0, result="next")), "next")

    async def test_direct_result_cancellation_also_cancels_operation(self):
        manager = JobManager(1)
        self.addAsyncCleanup(manager.close)
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        async def operation():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        handle = manager.submit(operation)
        await entered.wait()
        handle.result.cancel()
        await handle.finished
        self.assertTrue(cleaned.is_set())
        self.assertEqual(manager.active, 0)
