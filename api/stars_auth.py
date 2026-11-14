"""Domain-separated signed Stars bridge scopes for bot -> API requests.

HMAC signatures use the existing short-lived nonce/replay guard. Every byte of
a canonical bounded request body is covered by the signature scope.
"""
import hashlib
import json

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
