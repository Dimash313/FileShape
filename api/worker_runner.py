"""Execute untrusted file parsing in a separate bounded process.

The child process can be terminated on timeout, unlike asyncio.to_thread.
The API remains responsible for authentication, upload limits and cleanup.
"""
import asyncio
import json
import os
import signal
from pathlib import Path
import sys

WORKER_TIMEOUT_SECONDS = 45
WORKER_MEMORY_BYTES = 512 * 1024 * 1024
WORKER_OUTPUT_LIMIT = 64 * 1024


class WorkerTimeout(ValueError):
    pass


class WorkerFailed(ValueError):
    pass


def _resource_limits():
    """Linux-only limits, applied before executing the child interpreter."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (WORKER_MEMORY_BYTES, WORKER_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (WORKER_TIMEOUT_SECONDS + 2, WORKER_TIMEOUT_SECONDS + 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


async def _communicate_bounded(proc, data: bytes) -> bytes:
    """Read at most 64 KiB + 1 byte, even if a worker floods stdout.

    Unlike Process.communicate(), this does not accumulate unbounded output
    in the API process. Input is fed concurrently to avoid pipe deadlocks.
    """
    async def feed_input():
        try:
            proc.stdin.write(data)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # Workers may reject malformed requests before reading stdin.
            pass
        finally:
            proc.stdin.close()

    async def read_output():
        output = bytearray()
        while True:
            # Never request more than the budget plus one sentinel byte.
            chunk = await proc.stdout.read(min(16384, WORKER_OUTPUT_LIMIT + 1 - len(output)))
            if not chunk:
                return bytes(output)
            output.extend(chunk)
            if len(output) > WORKER_OUTPUT_LIMIT:
                raise WorkerFailed("Слишком большой ответ обработчика")

    writer = asyncio.create_task(feed_input())
    reader = asyncio.create_task(read_output())
    try:
        output = await reader
        await writer
        await proc.wait()
        return output
    finally:
        for task in (reader, writer):
            if not task.done():
                task.cancel()
        await asyncio.gather(reader, writer, return_exceptions=True)


async def run_worker(payload: dict, timeout: float = WORKER_TIMEOUT_SECONDS) -> dict:
    """Run one operation; kill and reap the worker on timeout or cancellation."""
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # A new POSIX session gives this job its own process group. Kill the
    # entire group on timeout/cancellation, including FFmpeg grandchildren.
    # Other platforms still get a wall-clock timeout for the direct child.
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    if sys.platform.startswith("linux"):
        kwargs["preexec_fn"] = _resource_limits
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "api.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        **kwargs,
    )
    try:
        try:
            stdout = await asyncio.wait_for(_communicate_bounded(proc, data), timeout=timeout)
        except asyncio.TimeoutError:
            raise WorkerTimeout("Обработка заняла слишком много времени") from None
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            raise WorkerFailed("Обработчик завершился без корректного ответа") from None
        if not isinstance(result, dict):
            raise WorkerFailed("Некорректный ответ обработчика")
        if proc.returncode != 0 or not result.get("ok"):
            detail = result.get("error", "Не удалось обработать файл")
            raise WorkerFailed(str(detail)[:200])
        return result
    finally:
        # Even if the worker already exited, a grandchild may still hold the
        # process group. Only signal our freshly-created POSIX session.
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.returncode is None:
            proc.kill()
        if proc.returncode is None:
            # Reap after cancellation without allowing a second cancellation
            # to abandon the subprocess.
            await asyncio.shield(proc.wait())
