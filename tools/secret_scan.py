"""No-network preflight for accidental credentials in Git-tracked files.

This is a high-confidence *current index* check, not a Git history scan,
credential revocation service or replacement for GitHub secret scanning.
Never print matched bytes or excerpts in an Actions job log.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MAX_TRACKED_FILES = 20_000
MAX_FILE_BYTES = 2 * 1024 * 1024
BINARY_EXTENSIONS = frozenset({
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".zip", ".gz", ".tar", ".mp3",
    ".mp4", ".wav", ".ogg", ".webm", ".mov", ".docx", ".xlsx",
})
PLACEHOLDER_ENV_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})

# Only high-confidence syntaxes. Do not add a generic "password=" regex:
# legitimate documentation and examples would trigger false positives.
TOKEN_RULES = (
    ("telegram_bot_token", re.compile(rb"(?<![A-Za-z0-9])\d{8,12}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("github_access_token", re.compile(rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{45,})(?![A-Za-z0-9_])")),
    ("aws_access_key_id", re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("pem_private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("openai_api_key", re.compile(rb"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")),
    ("stripe_secret_key", re.compile(rb"(?<![A-Za-z0-9_])sk_live_[A-Za-z0-9]{20,}(?![A-Za-z0-9])")),
    ("slack_secret_token", re.compile(rb"(?<![A-Za-z0-9_-])xox[baprs]-[A-Za-z0-9-]{20,}(?![A-Za-z0-9-])")),
)


def _sensitive_name(name: str) -> bool:
    base = Path(name).name.lower()
    if (base == ".env" or base.startswith(".env.")) and base not in PLACEHOLDER_ENV_NAMES:
        return True
    return base.endswith((".pem", ".p12", ".pfx", ".jks")) or base in (
        "id_rsa", "id_dsa", "id_ed25519", "id_ecdsa",
    )


def scan_file(root: Path, relative: str) -> tuple[str, ...]:
    """Return rule IDs only. No actual file bytes leave this function."""
    if _sensitive_name(relative):
        return ("tracked_private_file",)
    path = root / relative
    try:
        info = path.lstat()  # Never follow a tracked symlink to private paths.
        if stat.S_ISLNK(info.st_mode):
            return ("tracked_symlink_requires_review",)
        if not stat.S_ISREG(info.st_mode):
            return ("unsupported_tracked_entry",)
        if info.st_size > MAX_FILE_BYTES:
            if path.suffix.lower() in BINARY_EXTENSIONS:
                return ()
            return ("oversized_tracked_file",)
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return ("oversized_tracked_file",)
    except OSError:
        return ("unreadable_tracked_file",)
    # Scan bytes, not decoded text: ASCII token material embedded in unusual
    # encodings or binary metadata can still be detected without decoding.
    return tuple(rule for rule, pattern in TOKEN_RULES if pattern.search(data))


def _safe_path_label(relative: str) -> str:
    # A malicious filename may itself be a credential; redact that too.
    raw = os.fsencode(relative)
    if any(pattern.search(raw) for _, pattern in TOKEN_RULES):
        digest = hashlib.sha256(raw).hexdigest()[:12]
        return f"<redacted-path:{digest}>"
    # Prevent newlines/control chars in filenames from forging Actions logs.
    return ascii(relative)


def scan_repository(root: Path, *, output=None) -> int:
    """Return 0 for clear index, 1 for detections, 2 when scanning failed."""
    if output is None:
        output = sys.stdout
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=15,
        ).stdout.split(b"\0")
    except (OSError, subprocess.SubprocessError):
        print("secret-scan: git index unavailable", file=output)
        return 2
    paths = [os.fsdecode(raw) for raw in tracked if raw]
    if not paths or len(paths) > MAX_TRACKED_FILES:
        print("secret-scan: invalid tracked-file count", file=output)
        return 2
    flagged = 0
    for relative in paths:
        for rule in scan_file(root, relative):
            print(f"secret-scan: {rule} in {_safe_path_label(relative)}", file=output)
            flagged += 1
    if flagged:
        print(f"secret-scan: blocked ({flagged} finding(s), values withheld)", file=output)
        return 1
    print(f"secret-scan: passed ({len(paths)} tracked paths)", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(scan_repository(Path(__file__).resolve().parents[1]))
