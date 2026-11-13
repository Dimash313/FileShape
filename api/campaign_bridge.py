"""Authenticated one-worker Telegram bot -> API campaign join assertions.

The bot must derive these assertions from real chat_member updates only.
The API never trusts unauthenticated membership or campaign identifiers.
"""
import hashlib
import hmac
import json
import re
import time

from api.internal_access import WINDOW_SECONDS, MAX_NONCES

_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_INVITE = re.compile(r"https://t\.me/\+[A-Za-z0-9_-]{8,128}\Z")


def validate_join_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "chat_id", "invite_link", "user_digest", "joined_at"
    }:
        raise ValueError("Invalid join fields")
    if type(payload["chat_id"]) is not int or payload["chat_id"] >= 0 or payload["chat_id"] < -(2**63):
        raise ValueError("Invalid channel")
    if not isinstance(payload["invite_link"], str) or not _INVITE.fullmatch(payload["invite_link"]):
        raise ValueError("Invalid invite")
    if not isinstance(payload["user_digest"], str) or not _DIGEST.fullmatch(payload["user_digest"]):
        raise ValueError("Invalid digest")
    if type(payload["joined_at"]) is not int or payload["joined_at"] <= 0:
        raise ValueError("Invalid join timestamp")


def sign_join_assertion(token, payload, timestamp, nonce):
    validate_join_payload(payload)
    if not isinstance(token, str) or not token:
        raise ValueError("Missing token")
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("Invalid assertion time")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise ValueError("Invalid nonce")
    key = hmac.new(token.encode(), b"fileshape-campaign-join-v1", hashlib.sha256).digest()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hmac.new(key, f"v1:{timestamp}:{nonce}:{canonical}".encode("ascii"), hashlib.sha256).hexdigest()


class JoinReplayGuard:
    """Short-lived bounded nonce cache; safe for existing one-worker API."""
    def __init__(self):
        self._seen = {}

    def verify(self, token, payload, timestamp, nonce, signature, *, now=None):
        if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 16:
            raise ValueError("Invalid timestamp")
        if not isinstance(signature, str) or not _DIGEST.fullmatch(signature):
            raise ValueError("Invalid signature")
        if now is None:
            now = int(time.time())
        issued = int(timestamp)
        if abs(now - issued) > WINDOW_SECONDS:
            raise ValueError("Expired assertion")
        expected = sign_join_assertion(token, payload, issued, nonce)
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid signature")
        # The API handler calls verify and stores nonce without awaiting.
        if nonce in self._seen:
            raise ValueError("Replayed assertion")
        if len(self._seen) >= MAX_NONCES:
            self._seen = {k: v for k, v in self._seen.items() if v >= now}
        if len(self._seen) >= MAX_NONCES:
            raise ValueError("Replay cache full")
        self._seen[nonce] = now + WINDOW_SECONDS
        # A stale event cannot be used to backfill an already-ended campaign.
        if abs(now - payload["joined_at"]) > 300:
            raise ValueError("Stale membership event")
