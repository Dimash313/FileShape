"""Hard timeout, error and cancellation tests for worker isolation."""
import asyncio
import os
import shutil
import wave
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

    async def test_flooding_stdout_rejected_before_worker_exits(self):
        # The previous proc.communicate() buffered stdout until the deadline
        # instead of failing as soon as the 64 KiB cap was exceeded.
        original = asyncio.create_subprocess_exec
        processes = []
        script = (
            "import os,time\n"
            "while True:\n"
            " os.write(1,b'x'*8192)\n"
            " time.sleep(0.002)\n"
        )

        async def flood_process(*args, **kwargs):
            proc = await original(
                sys.executable, "-c", script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            processes.append(proc)
            return proc

        with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=flood_process):
            with self.assertRaisesRegex(WorkerFailed, "Слишком большой ответ"):
                await run_worker({"operation": "single"}, timeout=2)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode, "Flooding process was not reaped")

    async def test_exact_stdout_limit_accepts_valid_worker_json(self):
        from api.worker_runner import WORKER_OUTPUT_LIMIT
        original = asyncio.create_subprocess_exec
        script = (
            "import json,sys\n"
            "head=json.dumps({'ok':True,'padding':''})\n"
            f"count={WORKER_OUTPUT_LIMIT}-len(head.encode('utf-8'))\n"
            "sys.stdout.write(json.dumps({'ok':True,'padding':'x'*count}))\n"
        )

        async def valid_process(*args, **kwargs):
            return await original(
                sys.executable, "-c", script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )

        with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=valid_process):
            data = await run_worker({"operation": "single"}, timeout=5)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["padding"]) + len('{"ok": true, "padding": ""}'),
                         WORKER_OUTPUT_LIMIT)

    async def test_worker_subprocess_does_not_inherit_parent_secrets(self):
        # Exercise an actual child process rather than inspecting only the
        # keyword arguments passed to create_subprocess_exec.
        original = asyncio.create_subprocess_exec
        script = (
            "import json,os,sys\n"
            "sys.stdin.buffer.read()\n"
            "secrets=('BOT_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY',"
            "'FILESHAPE_PRIVATE_KEY','PYTHONPATH','PYTHONHOME',"
            "'PYTHONSTARTUP','LD_PRELOAD','LD_LIBRARY_PATH')\n"
            "sys.stdout.write(json.dumps({'ok':True,"
            "'leaked':[key for key in secrets if key in os.environ],"
            "'path':bool(os.getenv('PATH')),"
            "'dotenv':os.getenv('PYTHON_DOTENV_DISABLED'),"
            "'pythonio':os.getenv('PYTHONIOENCODING')}))\n"
        )

        async def inspect_child(*args, **kwargs):
            return await original(
                sys.executable, "-c", script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                env=kwargs["env"],
            )

        sentinels = {
            "BOT_TOKEN": "fake_bot_token",
            "GITHUB_TOKEN": "fake_github_token",
            "AWS_SECRET_ACCESS_KEY": "fake_aws_key",
            "FILESHAPE_PRIVATE_KEY": "fake_internal_secret",
            "PYTHONPATH": "/tmp/hostile",
            "PYTHONHOME": "/tmp/hostile",
            "PYTHONSTARTUP": "/tmp/hostile.py",
            "LD_PRELOAD": "/tmp/hostile.so",
            "LD_LIBRARY_PATH": "/tmp/hostile",
        }
        with patch.dict(os.environ, sentinels):
            with patch("api.worker_runner.asyncio.create_subprocess_exec", side_effect=inspect_child):
                response = await run_worker({"operation": "invalid"}, timeout=5)
        self.assertEqual(response["leaked"], [])
        self.assertTrue(response["path"])
        self.assertEqual(response["dotenv"], "1")
        self.assertEqual(response["pythonio"], "utf-8")

    def test_dotenv_will_not_reload_worker_bot_secret(self):
        from io import StringIO
        from dotenv import load_dotenv
        from api.worker_runner import _worker_environment

        worker_env = _worker_environment()
        self.assertEqual(worker_env["PYTHON_DOTENV_DISABLED"], "1")
        with patch.dict(os.environ, worker_env, clear=True):
            self.assertFalse(load_dotenv(stream=StringIO("BOT_TOKEN=secret_from_dotenv\n")))
            self.assertNotIn("BOT_TOKEN", os.environ)

    async def test_real_txt_to_docx_with_restricted_worker_environment(self):
        # Exercise the actual child import + converter stack, not a patched
        # subprocess that only echoes its environment.
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "source.txt").write_text("FileShape test document", encoding="utf-8")
            with patch.dict(os.environ, {
                "BOT_TOKEN": "fake_parent_bot_token",
                "FILESHAPE_PRIVATE_KEY": "fake_parent_secret",
                "PYTHONPATH": "/tmp/should-not-be-inherited",
            }):
                result = await run_worker({
                    "operation": "single",
                    "work": folder,
                    "suffix": ".txt",
                    "action": "txt:docx",
                    "pages": "",
                }, timeout=15)
            self.assertTrue(result["ok"])
            self.assertEqual(result["filename"], "converted.docx")
            output = work / result["filename"]
            self.assertGreater(output.stat().st_size, 0)
            from docx import Document
            document = Document(str(output))
            self.assertEqual(document.paragraphs[0].text, "FileShape test document")

    @unittest.skipUnless(shutil.which("ffprobe"), "FFprobe is required")
    async def test_real_silent_wav_probe_with_restricted_worker_environment(self):
        # Silence is sufficient; no recorded audio or musical content.
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            with wave.open(str(work / "source.wav"), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(16000)
                writer.writeframes(b"\\x00\\x00" * 8000)
            with patch.dict(os.environ, {
                "BOT_TOKEN": "fake_parent_bot_token",
                "GITHUB_TOKEN": "fake_parent_github_token",
                "LD_LIBRARY_PATH": "/tmp/untrusted-libs",
            }):
                result = await run_worker({
                    "operation": "single",
                    "work": folder,
                    "suffix": ".wav",
                    "action": "audio:info",
                    "pages": "",
                }, timeout=15)
            self.assertTrue(result["ok"])
            self.assertAlmostEqual(result["info"]["seconds"], 0.5, delta=0.2)

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
                    # Cold Python startup on loaded CI hosts can exceed 0.7s.
                    # Still verify group termination under a short deadline.
                    await run_worker({"operation": "single"}, timeout=2.0)

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
