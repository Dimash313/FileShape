"""Execute untrusted file parsing in a separate bounded process.

The child process can be terminated on timeout, unlike asyncio.to_thread.
The API remains responsible for authentication, upload limits and cleanup.
"""
import asyncio
import json
import os
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


async def run_worker(payload: dict, timeout: float = WORKER_TIMEOUT_SECONDS) -> dict:
    """Run one operation; kill and reap the worker on timeout or cancellation."""
    if timeout <= 0:
        raise ValueError("Timeout must be positive")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # preexec_fn is safe here because this API uses a single event-loop thread.
    # Other platforms still get a hard wall-clock timeout, without rlimits.
    kwargs = {"preexec_fn": _resource_limits} if sys.platform.startswith("linux") else {}
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
            stdout, _ = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
        except asyncio.TimeoutError:
            raise WorkerTimeout("Обработка заняла слишком много времени") from None
        if len(stdout) > WORKER_OUTPUT_LIMIT:
            raise WorkerFailed("Слишком большой ответ обработчика")
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
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()
