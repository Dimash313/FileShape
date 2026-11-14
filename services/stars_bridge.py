"""Private, scoped Telegram Stars bot-to-API bridge; no bot SQLite access."""
import asyncio
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import aiohttp

from api.internal_access import sign_access_request
from api.stars_auth import stars_scope


_ORDER = re.compile(r"[0-9a-f]{32}\Z")


class StarsBridgeUnavailable(Exception):
    """No verified server decision can be obtained."""


def checkout_enabled() -> bool:
    return os.getenv("FILESHAPE_STARS_CHECKOUT_ENABLED", "").strip().lower() == "true"


def _base_url() -> str:
    url = os.getenv("FILESHAPE_STARS_GATE_URL", "").strip()
    if not url:
        access = os.getenv("FILESHAPE_ACCESS_GATE_URL", "").strip()
        if access.endswith("/internal/v1/access/check"):
            url = access[: -len("/internal/v1/access/check")] + "/internal/v1/stars"
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path != "/internal/v1/stars"):
        raise StarsBridgeUnavailable("Stars API not configured")
    return url.rstrip("/")


async def _call(user_id: int, token: str, action: str, fields: dict, *, checkout=False) -> dict:
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise StarsBridgeUnavailable("Invalid Stars buyer")
    if checkout and not checkout_enabled():
        raise StarsBridgeUnavailable("Stars checkout disabled")
    try:
        scope = stars_scope(action, fields)
        url = _base_url()
    except (ValueError, TypeError) as exc:
        raise StarsBridgeUnavailable(str(exc)) from None
    # Pre-checkout must be answered within ten seconds, including network.
    timeout = aiohttp.ClientTimeout(total=4 if action == "precheckout" else 8, connect=2)
    retries = 1 if action == "precheckout" else 2
    for attempt in range(retries):
        nonce = secrets.token_hex(16)
        now = int(time.time())
        headers = {
            "X-FileShape-User": str(user_id),
            "X-FileShape-Time": str(now),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": sign_access_request(
                token, user_id, now, nonce, scope=scope,
            ),
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    url + "/" + ("refund-confirm" if action == "refund" else action), json=fields, headers=headers,
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise StarsBridgeUnavailable("Stars server returned an error")
                    result = await response.json(content_type="application/json")
                    if not isinstance(result, dict):
                        raise StarsBridgeUnavailable("Invalid Stars server response")
                    return result
        except StarsBridgeUnavailable:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError, TypeError):
            if attempt == retries - 1:
                raise StarsBridgeUnavailable("Stars server unreachable") from None
    raise StarsBridgeUnavailable("Stars server unavailable")


async def create_stars_quote(user_id: int, token: str, sku: str) -> dict:
    result = await _call(user_id, token, "quote", {"sku": sku}, checkout=True)
    if (not isinstance(result.get("order_id"), str)
            or _ORDER.fullmatch(result["order_id"]) is None
            or result.get("sku") != sku
            or result.get("currency") != "XTR"
            or type(result.get("amount")) is not int
            or result["amount"] <= 0 or result.get("status") != "pending"):
        raise StarsBridgeUnavailable("Invalid Stars quote")
    return result


async def approve_stars_checkout(user_id: int, token: str, order_id: str,
                                 amount: int, currency: str) -> bool:
    if not checkout_enabled():
        return False
    if not isinstance(order_id, str) or _ORDER.fullmatch(order_id) is None:
        return False
    result = await _call(
        user_id, token, "precheckout",
        {"order_id": order_id, "amount": amount, "currency": currency},
        checkout=True,
    )
    if type(result.get("approved")) is not bool:
        raise StarsBridgeUnavailable("Invalid pre-checkout reply")
    return result["approved"]


async def confirm_stars_payment(user_id: int, token: str, order_id: str,
                                amount: int, currency: str, charge_id: str) -> dict:
    if not isinstance(order_id, str) or _ORDER.fullmatch(order_id) is None:
        raise StarsBridgeUnavailable("Invalid payment invoice")
    result = await _call(
        user_id, token, "confirm",
        {"order_id": order_id, "amount": amount,
         "currency": currency, "charge_id": charge_id},
    )
    if (result.get("order_id") != order_id or result.get("status") != "fulfilled"
            or type(result.get("created")) is not bool):
        raise StarsBridgeUnavailable("Stars order not fulfilled")
    return result


async def confirm_stars_refund(user_id: int, token: str, charge_id: str) -> dict:
    """Call only after the official refundStarPayment method returns success."""
    result = await _call(
        user_id, token, "refund", {"charge_id": charge_id},
    )
    if result.get("status") != "refunded" or type(result.get("changed")) is not bool:
        raise StarsBridgeUnavailable("Stars refund not reconciled")
    return result
