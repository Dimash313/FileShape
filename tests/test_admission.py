"""Deterministic queue tests without external services or heavy workers."""
import asyncio
import unittest

from api.admission import AdmissionQueue, QueueClosed, QueueFull, QueueTimeout


class AdmissionQueueTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for_waiters(self, gate, count):
        for _ in range(200):
            if gate.waiting == count:
                return
            await asyncio.sleep(0.005)
        self.fail(f"Expected {count} waiting requests, found {gate.waiting}")

    async def test_ten_workers_allow_eleventh_to_wait(self):
        slots = asyncio.Semaphore(10)
        gate = AdmissionQueue(max_waiters=20, wait_seconds=1)
        for _ in range(10):
            await gate.acquire(slots)
        eleventh = asyncio.create_task(gate.acquire(slots))
        try:
            await self.wait_for_waiters(gate, 1)
            self.assertFalse(eleventh.done())
            slots.release()
            await asyncio.wait_for(eleventh, timeout=1)
            self.assertEqual(gate.waiting, 0)
        finally:
            if not eleventh.done():
                eleventh.cancel()
                await asyncio.gather(eleventh, return_exceptions=True)

    async def test_full_queue_refuses_more_requests(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=1, wait_seconds=1)
        pending = asyncio.create_task(gate.acquire(slots))
        try:
            await self.wait_for_waiters(gate, 1)
            with self.assertRaises(QueueFull):
                await gate.acquire(slots)
            self.assertEqual(gate.waiting, 1)
            slots.release()
            await pending
            self.assertEqual(gate.waiting, 0)
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def test_timeout_frees_waiting_place(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=1, wait_seconds=0.03)
        with self.assertRaises(QueueTimeout):
            await gate.acquire(slots)
        self.assertEqual(gate.waiting, 0)
        slots.release()
        await gate.acquire(slots)
        self.assertEqual(gate.waiting, 0)

    async def test_cancelled_waiter_does_not_block_next_request(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=1, wait_seconds=1)
        waiting = asyncio.create_task(gate.acquire(slots))
        await self.wait_for_waiters(gate, 1)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(gate.waiting, 0)
        slots.release()
        await gate.acquire(slots)

    async def test_shutdown_rejects_new_and_wakes_waiting_requests(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=2, wait_seconds=10)
        tasks = [asyncio.create_task(gate.acquire(slots)) for _ in range(2)]
        try:
            await self.wait_for_waiters(gate, 2)
            gate.close()
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 1)
            self.assertTrue(all(isinstance(result, QueueClosed) for result in results))
            self.assertEqual(gate.waiting, 0)
            with self.assertRaises(QueueClosed):
                await gate.acquire(slots)
            self.assertEqual(slots._value, 0)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_shutdown_acquire_race_does_not_leak_permit(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=1, wait_seconds=10)
        pending = asyncio.create_task(gate.acquire(slots))
        await self.wait_for_waiters(gate, 1)
        slots.release()
        gate.close()
        with self.assertRaises(QueueClosed):
            await asyncio.wait_for(pending, 1)
        self.assertEqual(gate.waiting, 0)
        self.assertEqual(slots._value, 1)

    async def test_waiters_run_in_arrival_order(self):
        slots = asyncio.Semaphore(1)
        await slots.acquire()
        gate = AdmissionQueue(max_waiters=3, wait_seconds=1)
        processed = []

        async def job(value):
            await gate.acquire(slots)
            processed.append(value)
            slots.release()

        tasks = []
        try:
            for number in (1, 2, 3):
                tasks.append(asyncio.create_task(job(number)))
                await self.wait_for_waiters(gate, number)
            slots.release()
            await asyncio.gather(*tasks)
            self.assertEqual(processed, [1, 2, 3])
            self.assertEqual(gate.waiting, 0)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class AdmissionMultiLoopTests(unittest.TestCase):
    def test_queue_handles_sequential_event_loops_without_false_shutdown(self):
        gate = AdmissionQueue(max_waiters=1, wait_seconds=1)

        async def acquire_in_new_loop():
            slots = asyncio.Semaphore(1)
            await gate.acquire(slots)
            slots.release()

        # TestClient runs requests on separate loops when not using lifespan.
        for _ in range(3):
            asyncio.run(acquire_in_new_loop())
        self.assertFalse(gate.closing)


if __name__ == "__main__":
    unittest.main()
