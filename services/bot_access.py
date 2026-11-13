"""Bounded bot-to-API access check; no SQLite handles in the bot process."""
import asyncio
import os
import secrets
import time
from urllib.parse import urlsplit

import aiohttp

from api.internal_access import sign_access_request


ACCESS_CHECK_URL_ENV = "FILESHAPE_ACCESS_GATE_URL"
_ACCESS_DECISIONS = {"allowed", "subscription_required", "verification_unavailable"}


async def check_processing_access(user_id: int, token: str, *, url: str | None = None) -> str:
    """Return an explicit decision; network errors fail closed.

    Standalone deployments without FILESHAPE_ACCESS_GATE_URL retain the
    historical bot behavior. Compose configures the internal URL by default.
    """
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        return "verification_unavailable"
    if url is None:
        url = os.getenv(ACCESS_CHECK_URL_ENV, "").strip()
    if not url:
        return "allowed"
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.query
                or parsed.path != "/internal/v1/access/check"):
            return "verification_unavailable"
        nonce = secrets.token_hex(16)
        issued_at = int(time.time())
        signature = sign_access_request(token, user_id, issued_at, nonce)
        headers = {
            "X-FileShape-User": str(user_id),
            "X-FileShape-Time": str(issued_at),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": signature,
        }
        timeout = aiohttp.ClientTimeout(total=15, connect=3)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.post(url, headers=headers, allow_redirects=False) as response:
                if response.status != 200:
                    return "verification_unavailable"
                payload = await response.json(content_type="application/json")
                if isinstance(payload, dict) and payload.get("decision") in _ACCESS_DECISIONS:
                    return payload["decision"]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, OSError):
        pass
    return "verification_unavailable"
