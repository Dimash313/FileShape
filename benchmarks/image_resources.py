"""Opt-in isolated benchmark of FileShape's real image-to-PDF implementation.

Examples:
    python benchmarks/image_resources.py --profile smoke
    python benchmarks/image_resources.py --profile typical
    python benchmarks/image_resources.py --profile near-cap --timeout 120

This is an operational measurement tool, not a CI performance gate. The
reported peak RSS is the child process's total peak, including imports and
decoder buffers, not an incremental memory measurement. Results vary by OS,
CPU, Python/Pillow versions and filesystem caching.
Only neutral solid-color synthetic inputs are generated.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from PIL import Image, __version__ as PILLOW_VERSION


ROOT = Path(__file__).resolve().parents[1]
# Running a file from benchmarks/ otherwise makes services/ unreachable.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (encoding, width, height) tuples; all profiles respect production bounds:
# 2-8 files, <=20 MiB encoded input, <=22m decoded pixels.
PROFILES = {
    "smoke": (("PNG", 96, 72), ("WEBP", 80, 104)),
    "typical": (("PNG", 640, 480), ("WEBP", 800, 600), ("JPEG", 720, 960)),
    "near-cap": (
        ("PNG", 1800, 1800), ("WEBP", 1800, 1800),
        ("JPEG", 1800, 1800), ("PNG", 1800, 1800),
        ("WEBP", 1800, 1800), ("JPEG", 1800, 1800),
    ),
}
EXTENSIONS = {"PNG": ".png", "WEBP": ".webp", "JPEG": ".jpg"}
MAX_INPUT_FILES = 8
MAX_TOTAL_PIXELS = 22_000_000
MAX_TOTAL_BYTES = 20 * 1024 * 1024


def validate_profile(profile: str) -> tuple:
    specs = PROFILES[profile]
    if not 2 <= len(specs) <= MAX_INPUT_FILES:
        raise ValueError("Invalid benchmark file count")
    total = 0
    for fmt, width, height in specs:
        if fmt not in EXTENSIONS or width < 1 or height < 1:
            raise ValueError("Invalid benchmark image specification")
        total += width * height
    if total > MAX_TOTAL_PIXELS:
        raise ValueError("Benchmark profile exceeds PDF pixel budget")
    return specs


def create_fixtures(directory: Path, profile: str) -> list[Path]:
    """Fixture creation happens in the *parent*, outside measured child RSS."""
    sources = []
    for i, (fmt, width, height) in enumerate(validate_profile(profile)):
        path = directory / f"input_{i:02d}{EXTENSIONS[fmt]}"
        mode = "RGBA" if fmt != "JPEG" else "RGB"
        color = (25 + i * 17, 75, 145, 185) if mode == "RGBA" else (25, 75, 145)
        image = Image.new(mode, (width, height), color)
        try:
            image.save(path, format=fmt)
        finally:
            image.close()
        sources.append(path)
    if sum(path.stat().st_size for path in sources) > MAX_TOTAL_BYTES:
        raise ValueError("Synthetic input unexpectedly exceeds the byte budget")
    return sources


def _measure_child(directory: Path, profile: str, memory_mib: int) -> dict:
    if sys.platform != "linux":
        raise RuntimeError("Peak RSS and RLIMIT_AS benchmark requires Linux")
    import resource

    if memory_mib < 256 or memory_mib > 4096:
        raise ValueError("Memory limit must be between 256 and 4096 MiB")
    limit = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    from services.image_module import image_module

    specs = validate_profile(profile)
    sources = [
        directory / f"input_{i:02d}{EXTENSIONS[fmt]}"
        for i, (fmt, _, _) in enumerate(specs)
    ]
    target = directory / "result.pdf"
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    pages = image_module.bundle_as_pdf(sources, target)
    cpu_seconds = time.process_time() - start_cpu
    elapsed_seconds = time.perf_counter() - start_wall
    if pages != len(specs) or not target.is_file():
        raise RuntimeError("Image module did not publish expected PDF pages")
    with target.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError("Image module produced invalid PDF header")
    result = {
        "profile": profile,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "cpu_seconds": round(cpu_seconds, 6),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3
        ),  # Linux ru_maxrss is KiB, unlike macOS.
        "memory_limit_mib": memory_mib,
        "input_count": len(sources),
        "total_input_pixels": sum(w * h for _, w, h in specs),
        "total_input_bytes": sum(p.stat().st_size for p in sources),
        "result_bytes": target.stat().st_size,
        "result_pages": pages,
        "formats": [fmt for fmt, _, _ in specs],
        "python": platform.python_version(),
        "pillow": PILLOW_VERSION,
        "platform": platform.system(),
        "rss_scope": "absolute child process peak including module imports",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--memory-mib", type=int, default=1024)
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_directory", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be 1-600 seconds")
    if not 256 <= args.memory_mib <= 4096:
        parser.error("--memory-mib must be 256-4096")
    if args._child:
        if args._directory is None:
            parser.error("child mode requires an input directory")
        print(json.dumps(_measure_child(args._directory, args.profile, args.memory_mib)))
        return 0

    if sys.platform != "linux":
        parser.error("benchmark requires Linux for resource-usage units and limits")

    with tempfile.TemporaryDirectory(prefix="fileshape_benchmark_") as dirname:
        directory = Path(dirname)
        create_fixtures(directory, args.profile)
        command = [
            sys.executable, str(Path(__file__).resolve()), "--_child",
            "--_directory", dirname, "--profile", args.profile,
            "--memory-mib", str(args.memory_mib),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=args.timeout,
                check=False, cwd=ROOT,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Benchmark child exceeded {args.timeout}s deadline"
            ) from error
        if completed.returncode != 0:
            raise RuntimeError(
                f"Benchmark child failed with status {completed.returncode}: "
                + completed.stderr[-1200:]
            )
        report = json.loads(completed.stdout)
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
