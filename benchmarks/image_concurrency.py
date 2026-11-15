"""Opt-in Linux concurrency benchmark for FileShape multi-image PDF workloads.

Runs 2-3 independent child processors against private synthetic fixtures.
Use --profile smoke for quick checks; near-cap is NEVER part of default CI.
Sampled simultaneous RSS excludes the parent and may miss brief peaks.
Do not interpret these samples as production memory or throughput limits.

Examples:
    python benchmarks/image_concurrency.py --workers 2 --profile smoke
    python benchmarks/image_concurrency.py --workers 2 --profile typical --fixture-style blocks
    python benchmarks/image_concurrency.py --workers 3 --profile near-cap --timeout 120
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.image_resources import (  # noqa: E402
    PROFILES,
    PILLOW_VERSION,
    create_fixtures,
    validate_profile,
)

SCRIPT = ROOT / "benchmarks" / "image_resources.py"


def _rss_bytes(pid: int) -> int:
    """Read one live Linux child RSS sample; missing exited process is zero."""
    try:
        line = (Path("/proc") / str(pid) / "statm").read_text(encoding="ascii")
    except FileNotFoundError:
        return 0
    fields = line.split()
    if len(fields) < 2:
        raise RuntimeError("Could not read Linux process RSS")
    return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")


def _terminate_children(processes: list[subprocess.Popen]) -> None:
    """Terminate independent process groups, and always reap the children."""
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    for process in processes:
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def run_parallel(
    profile: str,
    fixture_style: str,
    workers: int,
    memory_mib: int,
    timeout: int,
    interval_ms: int,
    aggregate_memory_mib: int = 1024,
) -> dict:
    if sys.platform != "linux" or not Path("/proc/self/statm").is_file():
        raise RuntimeError("Concurrent RSS sampling requires Linux procfs")
    if workers not in (2, 3):
        raise ValueError("Only 2 or 3 workers are supported")
    if fixture_style not in ("solid", "blocks"):
        raise ValueError("Unsupported fixture style")
    if profile not in PROFILES:
        raise ValueError("Unsupported profile")
    if not 256 <= memory_mib <= 4096:
        raise ValueError("Child memory limit must be 256-4096 MiB")
    if not 1 <= timeout <= 600:
        raise ValueError("Worker timeout must be 1-600 seconds")
    if not 5 <= interval_ms <= 1000:
        raise ValueError("Sampling interval must be 5-1000 ms")
    if not 256 <= aggregate_memory_mib <= 4096:
        raise ValueError("Sampled aggregate budget must be 256-4096 MiB")
    validate_profile(profile)

    with tempfile.TemporaryDirectory(prefix="fileshape_concurrency_") as rootname:
        root = Path(rootname)
        workdirs = []
        for idx in range(workers):
            directory = root / f"worker_{idx}"
            directory.mkdir(mode=0o700)
            create_fixtures(directory, profile, fixture_style)
            workdirs.append(directory)

        processes: list[subprocess.Popen] = []
        start = time.perf_counter()
        deadline = time.monotonic() + timeout
        peak_sampled = 0
        samples = 0
        try:
            for directory in workdirs:
                command = [
                    sys.executable, str(SCRIPT),
                    "--_child", "--_directory", str(directory),
                    "--profile", profile, "--fixture-style", fixture_style,
                    "--memory-mib", str(memory_mib),
                ]
                processes.append(subprocess.Popen(
                    command, cwd=ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, start_new_session=True,
                ))

            # The children start together; per-job process times include only
            # PDF transformation, excluding imports and fixture preparation.
            while True:
                total_rss = sum(_rss_bytes(p.pid) for p in processes)
                peak_sampled = max(peak_sampled, total_rss)
                samples += 1
                if total_rss > aggregate_memory_mib * 1024 * 1024:
                    raise MemoryError("Sampled child RSS exceeded aggregate budget")
                if all(p.poll() is not None for p in processes):
                    break
                if any(p.poll() not in (None, 0) for p in processes):
                    raise RuntimeError("A benchmark child exited unsuccessfully")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Concurrent benchmark exceeded {timeout}s")
                time.sleep(interval_ms / 1000)

            reports = []
            for index, process in enumerate(processes):
                out, err = process.communicate(timeout=5)
                if process.returncode != 0:
                    raise RuntimeError(
                        f"Benchmark worker {index} exited {process.returncode}: "
                        + err[-900:]
                    )
                result = json.loads(out)
                if result.get("result_pages") != len(PROFILES[profile]):
                    raise RuntimeError("Benchmark worker returned wrong page count")
                if result.get("fixture_style") != fixture_style:
                    raise RuntimeError("Benchmark worker returned wrong fixture style")
                reports.append(result)
            elapsed = time.perf_counter() - start
            for directory in workdirs:
                if not (directory / "result.pdf").is_file():
                    raise RuntimeError("Missing benchmark result")
                if list(directory.glob(".fileshape_image_*")):
                    raise RuntimeError("Temporary output stage survived")
            return {
                "profile": profile,
                "fixture_style": fixture_style,
                "workers": workers,
                "elapsed_seconds": round(elapsed, 6),
                "total_cpu_seconds": round(
                    sum(x["cpu_seconds"] for x in reports), 6
                ),
                "peak_sampled_children_rss_mib": round(
                    peak_sampled / (1024 * 1024), 3
                ),
                "sum_individual_peak_rss_mib": round(
                    sum(x["peak_rss_mib"] for x in reports), 3
                ),
                "sample_count": samples,
                "sample_interval_ms": interval_ms,
                "per_child_memory_limit_mib": memory_mib,
                "aggregate_sample_budget_mib": aggregate_memory_mib,
                "input_pixels_per_worker": sum(
                    w * h for _, w, h in PROFILES[profile]
                ),
                "python": platform.python_version(),
                "pillow": PILLOW_VERSION,
                "platform": "Linux",
                "rss_scope": (
                    "sampled simultaneous children only; excludes parent and "
                    "other processes; sampled peak may miss brief maxima"
                ),
                "results": reports,
            }
        finally:
            _terminate_children(processes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--fixture-style", choices=("solid", "blocks"), default="solid")
    parser.add_argument("--workers", type=int, choices=(2, 3), default=2)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--interval-ms", type=int, default=25)
    parser.add_argument("--aggregate-memory-mib", type=int, default=1024)
    args = parser.parse_args(argv)
    try:
        report = run_parallel(
            args.profile, args.fixture_style, args.workers,
            args.memory_mib, args.timeout, args.interval_ms,
            args.aggregate_memory_mib,
        )
    except (ValueError, RuntimeError, TimeoutError, MemoryError) as error:
        parser.exit(status=1, message=f"{error}\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
