"""Short-lived, signed bot-to-API access assertions.

Only the Telegram bot process can assert user IDs. A separate bridge key is
derived from the existing BOT_TOKEN; no user input or file bytes are signed.
The API is the sole owner of durable entitlement/channel configuration.
"""
import hashlib
import hmac
import re
import time


WINDOW_SECONDS = 30
MAX_NONCES = 10_000
_NONCE_RE = re.compile(r"[0-9a-f]{32}")
_SIG_RE = re.compile(r"[0-9a-f]{64}")
_SCOPE_RE = re.compile(r"[a-z0-9:_-]{1,128}\Z")


def sign_access_request(token: str, user_id: int, timestamp: int, nonce: str, *, scope: str | None = None) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("Missing signing token")
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise ValueError("Invalid user")
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("Invalid timestamp")
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        raise ValueError("Invalid nonce")
    if scope is not None and (not isinstance(scope, str) or _SCOPE_RE.fullmatch(scope) is None):
        raise ValueError("Invalid signed operation scope")
    context = b"fileshape-internal-access-v1" if scope is None else b"fileshape-internal-operation-v1"
    key = hmac.new(token.encode("utf-8"), context, hashlib.sha256).digest()
    payload = (
        f"v1:{user_id}:{timestamp}:{nonce}" if scope is None
        else f"v2:{user_id}:{timestamp}:{nonce}:{scope}"
    ).encode("ascii")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


class ReplayGuard:
    """Single-process replay defense; deploy the existing one-worker API."""
    def __init__(self):
        self._seen: dict[str, int] = {}

    def verify(self, *, token: str, user: str, timestamp: str, nonce: str,
               signature: str, now: int | None = None, scope: str | None = None) -> int:
        if not isinstance(user, str) or not user.isascii() or not user.isdecimal():
            raise ValueError("Invalid user")
        if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdecimal():
            raise ValueError("Invalid timestamp")
        if len(user) > 19 or len(timestamp) > 16:
            raise ValueError("Invalid input length")
        if not isinstance(signature, str) or not _SIG_RE.fullmatch(signature):
            raise ValueError("Invalid signature")
        user_id, issued_at = int(user), int(timestamp)
        if now is None:
            now = int(time.time())
        if abs(now - issued_at) > WINDOW_SECONDS:
            raise ValueError("Expired access assertion")
        expected = sign_access_request(token, user_id, issued_at, nonce, scope=scope)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        # There is no await between replay lookup and registration in the API
        # handler: the event loop serializes these critical sections.
        if nonce in self._seen:
            raise ValueError("Replayed assertion")
        if len(self._seen) >= MAX_NONCES:
            self._seen = {key: exp for key, exp in self._seen.items() if exp >= now}
        if len(self._seen) >= MAX_NONCES:
            raise ValueError("Replay buffer at capacity")
        self._seen[nonce] = now + WINDOW_SECONDS
        return user_id
