"""Forward authenticated Telegram chat_member joins to the API-owned ledger."""
import asyncio
import logging
import os
import secrets
import time
from urllib.parse import urlsplit

import aiohttp

from api.campaign_bridge import sign_join_assertion
from services.campaign_telegram import keyed_member_digest, parse_confirmed_join

logger = logging.getLogger(__name__)
JOIN_URL_ENV = "FILESHAPE_CAMPAIGN_JOIN_URL"


async def forward_campaign_join(event, token: str, *, url: str | None = None) -> bool:
    """Return True only when the API confirms a newly counted join.

    A network failure does not imply a join was recorded. Durable delivery
    and retries require a future outbox; never invent a success result.
    """
    parsed = parse_confirmed_join(event)
    if parsed is None:
        return False
    if url is None:
        url = os.getenv(JOIN_URL_ENV, "").strip()
    if not url:
        logger.warning("Campaign join bridge not configured")
        return False
    target = urlsplit(url)
    if (target.scheme not in {"http", "https"} or not target.hostname
            or target.username or target.password or target.query or target.fragment
            or target.path != "/internal/v1/campaigns/join"):
        raise ValueError("Invalid campaign bridge URL")
    payload = {
        "chat_id": parsed.chat_id,
        "invite_link": parsed.invite_link,
        "user_digest": keyed_member_digest(token, parsed.member_id),
        "joined_at": parsed.event_time,
    }
    nonce = secrets.token_hex(16)
    timestamp = int(time.time())
    headers = {
        "X-FileShape-Time": str(timestamp),
        "X-FileShape-Nonce": nonce,
        "X-FileShape-Signature": sign_join_assertion(token, payload, timestamp, nonce),
    }
    try:
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.post(url, json=payload, headers=headers, allow_redirects=False) as response:
                if response.status != 200:
                    logger.warning("Campaign join API returned HTTP %s", response.status)
                    return False
                data = await response.json(content_type="application/json")
                return isinstance(data, dict) and data.get("recorded") is True
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
        logger.warning("Campaign join API unavailable")
        return False
