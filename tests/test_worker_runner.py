"""Hard timeout, error and cancellation tests for worker isolation."""
import asyncio
import sys
import unittest
from unittest.mock import patch

from api.worker_runner import WorkerFailed, WorkerTimeout, run_worker


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_worker_error(self):
        with self.assertRaises(WorkerFailed):
            await run_worker({"operation": "invalid", "work": "/tmp"}, timeout=10)

    async def test_timeout_kills_child(self):
        original = asyncio.create_subprocess_exec

        async def slow_process(*args, **kwargs):
            return await original(
                sys.executable, "-c",
                "import time; time.sleep(30)",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

        with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=slow_process):
            with self.assertRaises(WorkerTimeout):
                await run_worker({"operation": "single"}, timeout=0.1)

    async def test_cancel_kills_child(self):
        original = asyncio.create_subprocess_exec
        processes = []

        async def slow_process(*args, **kwargs):
            proc = await original(
                sys.executable, "-c", "import time; time.sleep(30)",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            processes.append(proc)
            return proc

        with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=slow_process):
            task = asyncio.create_task(run_worker({"operation": "single"}, timeout=15))
            await asyncio.sleep(0.1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)


if __name__ == "__main__":
    unittest.main()
