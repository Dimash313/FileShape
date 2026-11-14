"""Signed Telegram-bot processing leases backed by the API-owned quota ledger.

No bot-side SQLite connection, no optimistic local balance and no bypass if
the internal metering service is missing. The opaque request ID is retried
unchanged so a lost response cannot create multiple quota claims.
"""
import asyncio
import math
from datetime import date
import logging
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import aiohttp

from api.internal_access import sign_access_request


logger = logging.getLogger(__name__)
_JOB_RE = re.compile(r"[A-Za-z0-9_-]{16,100}\Z")


class BotOperationUnavailable(Exception):
    """Metering is unavailable; no file may be processed."""


class BotOperationQuotaExceeded(Exception):
    """The API rejected processing due to quota or active-operation limit."""


def _operation_base() -> str:
    base = os.getenv("FILESHAPE_OPERATION_GATE_URL", "").strip()
    if not base:
        access = os.getenv("FILESHAPE_ACCESS_GATE_URL", "").strip()
        if access.endswith("/internal/v1/access/check"):
            base = access[: -len("/internal/v1/access/check")] + "/internal/v1/operations"
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path != "/internal/v1/operations"):
        raise BotOperationUnavailable("Internal quota gate is not configured")
    return base.rstrip("/")


async def _call(user_id: int, token: str, action: str, fields: dict, scope: str) -> dict:
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise BotOperationUnavailable("Invalid owner")
    base = _operation_base()
    issued_at = int(time.time())
    nonce = secrets.token_hex(16)
    signature = sign_access_request(token, user_id, issued_at, nonce, scope=scope)
    headers = {
        "X-FileShape-User": str(user_id),
        "X-FileShape-Time": str(issued_at),
        "X-FileShape-Nonce": nonce,
        "X-FileShape-Signature": signature,
    }
    timeout = aiohttp.ClientTimeout(total=16, connect=3)
    # A fresh nonce/signature is generated per retry; the JSON request ID
    # remains stable across attempts and therefore cannot double-charge.
    for attempt in range(2):
        if attempt:
            issued_at = int(time.time())
            nonce = secrets.token_hex(16)
            headers["X-FileShape-Time"] = str(issued_at)
            headers["X-FileShape-Nonce"] = nonce
            headers["X-FileShape-Signature"] = sign_access_request(
                token, user_id, issued_at, nonce, scope=scope
            )
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    base + "/" + action, json=fields, headers=headers,
                    allow_redirects=False,
                ) as response:
                    if response.status == 429:
                        raise BotOperationQuotaExceeded()
                    if response.status != 200:
                        raise BotOperationUnavailable("Operation gate rejected request")
                    result = await response.json(content_type="application/json")
                    if not isinstance(result, dict):
                        raise BotOperationUnavailable("Invalid operation gate response")
                    return result
        except BotOperationQuotaExceeded:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError):
            if attempt == 1:
                raise BotOperationUnavailable("Operation gate unreachable") from None
    raise BotOperationUnavailable("Operation gate unavailable")


async def reserve_bot_operation(user_id: int, token: str) -> str:
    request_id = secrets.token_hex(16)
    payload = await _call(
        user_id, token, "reserve", {"request_id": request_id},
        "reserve:" + request_id,
    )
    job_id = payload.get("job_id")
    if (not isinstance(job_id, str) or _JOB_RE.fullmatch(job_id) is None
            or payload.get("state") != "processing"):
        raise BotOperationUnavailable("Invalid reservation confirmation")
    # A replay of the same bot request may follow a lost HTTP response.
    # It is still the same quota-backed operation, never a second debit.
    return job_id


async def settle_bot_operation(user_id: int, token: str, job_id: str, success: bool) -> None:
    if not isinstance(job_id, str) or _JOB_RE.fullmatch(job_id) is None or type(success) is not bool:
        raise BotOperationUnavailable("Invalid settlement request")
    expected = "completed" if success else "failed"
    payload = await _call(
        user_id, token, "settle", {"job_id": job_id, "success": success},
        "settle:" + job_id + (":1" if success else ":0"),
    )
    if payload.get("job_id") != job_id or payload.get("state") != expected:
        raise BotOperationUnavailable("Unexpected terminal operation state")


async def fetch_bot_usage(user_id: int, token: str) -> dict:
    """Read trusted API usage only; never infer balances from client state."""
    snapshot = await _call(user_id, token, "usage", {}, "usage")
    plan = snapshot.get("plan")
    day = snapshot.get("day_utc")
    limit = 100 if plan == "pro" else 10 if plan == "free" else None
    if limit is None or not isinstance(day, str) or len(day) != 10:
        raise BotOperationUnavailable("Invalid usage profile")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Noncanonical day")
    except ValueError:
        raise BotOperationUnavailable("Invalid usage date") from None
    used, remaining = snapshot.get("daily_used"), snapshot.get("daily_remaining")
    pack = snapshot.get("pack_remaining")
    expiry = snapshot.get("pro_expires_at")
    if (
        type(snapshot.get("daily_limit")) is not int
        or snapshot["daily_limit"] != limit
        or type(used) is not int or not 0 <= used <= limit
        or type(remaining) is not int or remaining != limit - used
        or type(pack) is not int or not 0 <= pack <= 10000
        or type(snapshot.get("enforced")) is not bool
        or type(snapshot.get("purchases_enabled")) is not bool
        or not snapshot["enforced"]
    ):
        raise BotOperationUnavailable("Usage enforcement not confirmed")
    if plan == "pro":
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or not 0 < expiry <= 253402300799:
            raise BotOperationUnavailable("Invalid Pro expiry")
    elif expiry is not None:
        raise BotOperationUnavailable("Unexpected Pro expiry")
    return {
        "plan": plan, "day_utc": day, "daily_limit": limit,
        "daily_used": used, "daily_remaining": remaining,
        "pack_remaining": pack, "pro_expires_at": expiry,
        "purchases_enabled": snapshot["purchases_enabled"],
    }
