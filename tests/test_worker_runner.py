"""Hard timeout, error and cancellation tests for worker isolation."""
import asyncio
import os
import tempfile
from pathlib import Path
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
                start_new_session=True,
            )

        with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=slow_process):
            with self.assertRaises(WorkerTimeout):
                await run_worker({"operation": "single"}, timeout=0.1)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux /proc")
    async def test_timeout_kills_grandchild(self):
        original = asyncio.create_subprocess_exec
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "grandchild.pid"
            script = (
                "import subprocess,sys,time;"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']);"
                "open(sys.argv[1],'w').write(str(p.pid));"
                "time.sleep(30)"
            )

            async def spawn_tree(*args, **kwargs):
                return await original(
                    sys.executable, "-c", script, str(pidfile),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )

            with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=spawn_tree):
                with self.assertRaises(WorkerTimeout):
                    await run_worker({"operation": "single"}, timeout=0.7)

            self.assertTrue(pidfile.exists(), "Grandchild was not started")
            pid = int(pidfile.read_text())
            # A killed grandchild can remain briefly as a zombie until reaped
            # by the container's init; it must not be running.
            for _ in range(30):
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().split()[2]
                except FileNotFoundError:
                    break
                if state == "Z":
                    break
                await asyncio.sleep(0.05)
            else:
                self.fail("Grandchild remains running after worker timeout")

    async def test_cancel_kills_child(self):
        original = asyncio.create_subprocess_exec
        processes = []

        async def slow_process(*args, **kwargs):
            proc = await original(
                sys.executable, "-c", "import time; time.sleep(30)",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
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
