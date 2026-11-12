"""Bounded, dependency-aware readiness checks for FileShape API.

Health (liveness) stays lightweight; readiness indicates whether the
instance can accept work. No credentials, paths or user data are exposed.
"""
from pathlib import Path
import shutil
import tempfile

REQUIRED_EXECUTABLES = ("ffmpeg", "ffprobe")


def readiness_status() -> dict:
    checks: dict[str, bool] = {}
    for name in REQUIRED_EXECUTABLES:
        checks[name] = shutil.which(name) is not None

    try:
        with tempfile.TemporaryDirectory(prefix="fileshape_ready_") as folder:
            path = Path(folder) / "write-test"
            path.write_bytes(b"ok")
            checks["temporary_storage"] = path.read_bytes() == b"ok"
    except (OSError, PermissionError):
        checks["temporary_storage"] = False

    return {"status": "ready" if all(checks.values()) else "unavailable", "checks": checks}
