"""Signed Stars bot bridge does not trust unsigned prices or require paid checkout."""
import os
import unittest
from unittest.mock import patch

from api.internal_access import ReplayGuard
from api.stars_auth import stars_scope
from services.stars_bridge import (
    StarsBridgeUnavailable, approve_stars_checkout, checkout_enabled,
    confirm_stars_payment, confirm_stars_refund, create_stars_quote,
)

TOKEN = "123456:TEST"
USER = 10901
ORDER = "f" * 32
BASE = "http://api:8000/internal/v1/stars"


class AsyncScope:
    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        return self.result

    async def __aexit__(self, *args):
        return False


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data

    async def json(self, **kwargs):
        return self.data


class Session:
    def __init__(self, response):
        self.response = response
        self.url = None
        self.data = None
        self.headers = None
        self.redirects = None

    def post(self, url, *, json, headers, allow_redirects):
        self.url, self.data = url, json
        self.headers, self.redirects = headers, allow_redirects
        return AsyncScope(self.response)


class StarsBridgeClientTests(unittest.IsolatedAsyncioTestCase):
    def env(self, *, enabled=True):
        return patch.dict(os.environ, {
            "FILESHAPE_STARS_GATE_URL": BASE,
            "FILESHAPE_ACCESS_GATE_URL": "",
            "FILESHAPE_STARS_CHECKOUT_ENABLED": "true" if enabled else "false",
            "FILESHAPE_SUPPORT_USERNAME": "FileShapeHelp",
        })

    def assert_signed(self, session, action):
        h = session.headers
        self.assertNotIn(TOKEN, str(h))
        self.assertFalse(session.redirects)
        ReplayGuard().verify(
            token=TOKEN, user=h["X-FileShape-User"],
            timestamp=h["X-FileShape-Time"], nonce=h["X-FileShape-Nonce"],
            signature=h["X-FileShape-Signature"],
            scope=stars_scope(action, session.data),
            now=int(h["X-FileShape-Time"]),
        )

    async def test_signed_quote_has_exact_server_catalog_price(self):
        quote = {
            "order_id": ORDER, "sku": "pack_10",
            "amount": 19, "currency": "XTR", "status": "pending",
        }
        session = Session(FakeResponse(data=quote))
        with self.env(), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(session),
        ):
            self.assertTrue(checkout_enabled())
            result = await create_stars_quote(USER, TOKEN, "pack_10")
        self.assertEqual(result, quote)
        self.assertEqual(session.url, BASE + "/quote")
        self.assertEqual(session.data, {"sku": "pack_10"})
        self.assert_signed(session, "quote")

    async def test_stars_precheckout_guard_and_scoped_decision(self):
        session = Session(FakeResponse(data={"approved": True}))
        with self.env(enabled=False), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(session),
        ) as factory:
            self.assertFalse(await approve_stars_checkout(USER, TOKEN, ORDER, 19, "XTR"))
            factory.assert_not_called()
        with self.env(), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(session),
        ):
            self.assertTrue(await approve_stars_checkout(USER, TOKEN, ORDER, 19, "XTR"))
        self.assertEqual(session.url, BASE + "/precheckout")
        self.assert_signed(session, "precheckout")

    async def test_paid_receipt_and_refund_are_forwarded_after_checkout_disabled(self):
        session = Session(FakeResponse(data={
            "order_id": ORDER, "status": "fulfilled",
            "sku": "pack_10", "created": True,
        }))
        with self.env(enabled=False), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(session),
        ):
            result = await confirm_stars_payment(
                USER, TOKEN, ORDER, 19, "XTR", "charge_001",
            )
        self.assertTrue(result["created"])
        self.assertEqual(session.url, BASE + "/confirm")
        self.assert_signed(session, "confirm")

        refund = Session(FakeResponse(data={
            "order_id": ORDER, "sku": "pack_10",
            "status": "refunded", "changed": True,
        }))
        with self.env(enabled=False), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(refund),
        ):
            await confirm_stars_refund(USER, TOKEN, "charge_001")
        self.assertEqual(refund.url, BASE + "/refund-confirm")
        self.assert_signed(refund, "refund")

    async def test_invalid_price_response_missing_gate_and_http_error_fail_closed(self):
        invalid = Session(FakeResponse(data={
            "order_id": ORDER, "sku": "pack_10",
            "amount": 19.5, "currency": "XTR", "status": "pending",
        }))
        with self.env(), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(invalid),
        ):
            with self.assertRaises(StarsBridgeUnavailable):
                await create_stars_quote(USER, TOKEN, "pack_10")
        broken = Session(FakeResponse(status=503))
        with self.env(), patch(
            "services.stars_bridge.aiohttp.ClientSession", return_value=AsyncScope(broken),
        ):
            with self.assertRaises(StarsBridgeUnavailable):
                await create_stars_quote(USER, TOKEN, "pack_10")
        with patch.dict(os.environ, {
            "FILESHAPE_STARS_GATE_URL": "",
            "FILESHAPE_ACCESS_GATE_URL": "",
        }):
            with self.assertRaises(StarsBridgeUnavailable):
                await confirm_stars_payment(USER, TOKEN, ORDER, 19, "XTR", "charge")

    def test_valid_support_contact_required_for_checkout(self):
        with self.env():
            self.assertTrue(checkout_enabled())
            with patch.dict(os.environ, {"FILESHAPE_SUPPORT_USERNAME": "bad value"}):
                self.assertFalse(checkout_enabled())
            with patch.dict(os.environ, {"FILESHAPE_SUPPORT_USERNAME": ""}):
                self.assertFalse(checkout_enabled())


if __name__ == "__main__":
    unittest.main()
