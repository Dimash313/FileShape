"""Domain-separated signed Stars bridge scopes for bot -> API requests.

HMAC signatures use the existing short-lived nonce/replay guard. Every byte of
a canonical bounded request body is covered by the signature scope.
"""
import hashlib
import json
import os
import re

ACTIONS = frozenset({"quote", "precheckout", "confirm", "refund"})


def stars_scope(action: str, fields: dict) -> str:
    if action not in ACTIONS or not isinstance(fields, dict):
        raise ValueError("Invalid Stars scope")
    blob = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(blob) > 512:
        raise ValueError("Stars request too large")
    digest = hashlib.sha256(
        b"fileshape-stars-v1:" + action.encode("ascii") + b":" + blob.encode("ascii")
    ).hexdigest()
    return "stars:" + action + ":" + digest

_SUPPORT_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")


def support_username() -> str | None:
    """An actual configured human-accessible support contact is mandatory."""
    raw = os.environ.get("FILESHAPE_SUPPORT_USERNAME", "").strip().lstrip("@")
    if _SUPPORT_USERNAME.fullmatch(raw) is None:
        return None
    return "@" + raw


def checkout_enabled() -> bool:
    """Opt in explicitly, and fail closed without payment support contact."""
    return (
        os.environ.get("FILESHAPE_STARS_CHECKOUT_ENABLED", "").strip().lower() == "true"
        and support_username() is not None
    )
