"""Signed internal Stars bridge: no public payment grants or forged receipts."""
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException
import httpx

from api import server
from api.durable_jobs import DurableJobStore
from api.internal_access import ReplayGuard, sign_access_request
from api.stars_auth import stars_scope
from api.stars_orders import PRODUCTS

TOKEN = "123456:TEST"
OWNER = 31001


class StarsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DurableJobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.addCleanup(self.store.close)
        for p in (
            patch.object(server, "jobs", self.store),
            patch.object(server, "job_runtime", object()),
            patch.object(server, "get_settings", return_value=SimpleNamespace(bot_token=TOKEN)),
            patch.object(server, "internal_bot_operation_replay", ReplayGuard()),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.api),
            base_url="http://test.internal",
        )
        self.addAsyncCleanup(self.client.aclose)

    def headers(self, action, data, *, owner=OWNER, token=TOKEN, nonce=None):
        issued = int(time.time())
        nonce = nonce or secrets.token_hex(16)
        return {
            "X-FileShape-User": str(owner),
            "X-FileShape-Time": str(issued),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": sign_access_request(
                token, owner, issued, nonce, scope=stars_scope(action, data),
            ),
        }

    async def post(self, action, data, *, owner=OWNER, token=TOKEN, nonce=None):
        path = "refund-confirm" if action == "refund" else action
        return await self.client.post(
            "/internal/v1/stars/" + path,
            json=data, headers=self.headers(action, data, owner=owner, token=token, nonce=nonce),
        )

    async def test_quote_gate_closed_by_default_and_bad_signature_rejected(self):
        with patch.dict(os.environ, {"FILESHAPE_STARS_CHECKOUT_ENABLED": ""}):
            data = {"sku": "pack_10"}
            denied = await self.post("quote", data)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM stars_orders").fetchone()[0], 0)
            spoof = await self.post("quote", data, token="wrong-token")
            self.assertEqual(spoof.status_code, 401)
            self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM stars_orders").fetchone()[0], 0)

    async def test_quote_check_confirmation_and_replayed_receipt(self):
        with patch.dict(os.environ, {"FILESHAPE_STARS_CHECKOUT_ENABLED": "true", "FILESHAPE_SUPPORT_USERNAME": "FileShapeHelp"}):
            quote = await self.post("quote", {"sku": "pack_10"})
            self.assertEqual(quote.status_code, 200, quote.text)
            order = quote.json()
            self.assertEqual(order["amount"], 19)
            self.assertEqual(order["currency"], "XTR")
            check = {"order_id": order["order_id"], "amount": 19, "currency": "XTR"}
            self.assertEqual((await self.post("precheckout", check)).json(), {"approved": True})
            self.assertEqual((await self.post("precheckout", {**check, "amount": 20})).json(), {"approved": False})
            self.assertEqual((await self.post("precheckout", check, owner=OWNER + 1)).json(), {"approved": False})
            self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 0)

        # Once the Telegram receipt arrives, must fulfill even when sales paused.
        data = {**check, "charge_id": "telegram:charge:10"}
        with patch.dict(os.environ, {"FILESHAPE_STARS_CHECKOUT_ENABLED": ""}):
            paid = await self.post("confirm", data)
            self.assertEqual(paid.status_code, 200, paid.text)
            self.assertEqual(paid.json(), {
                "order_id": order["order_id"], "sku": "pack_10",
                "status": "fulfilled", "created": True,
            })
            repeat = await self.post("confirm", data)
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertFalse(repeat.json()["created"])
            self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 10)
            self.assertEqual(
                (await self.post("precheckout", check)).json(), {"approved": False}
            )
        self.assertEqual(paid.headers["cache-control"], "no-store")

    async def test_flooded_quote_requests_are_capped_without_paid_grants(self):
        with (
            patch.dict(os.environ, {
                "FILESHAPE_STARS_CHECKOUT_ENABLED": "true",
                "FILESHAPE_SUPPORT_USERNAME": "FileShapeHelp",
            }),
            patch.object(server, "enforce_rate_limit", new_callable=AsyncMock),
        ):
            for _ in range(5):
                item = await self.post("quote", {"sku": "pack_10"})
                self.assertEqual(item.status_code, 200, item.text)
            blocked = await self.post("quote", {"sku": "pack_10"})
        self.assertEqual(blocked.status_code, 429, blocked.text)
        self.assertEqual(self.store._db.execute(
            "SELECT COUNT(*) FROM stars_orders WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 5)
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 0)
        self.assertIsNone(self.store.premium_expiry(OWNER))

    async def test_tampered_claim_replay_and_refund(self):
        order = self.store.create_stars_order(OWNER, "pack_30")
        data = {
            "order_id": order["order_id"], "amount": 49,
            "currency": "XTR", "charge_id": "telegram:global:42",
        }
        unsigned = await self.client.post("/internal/v1/stars/confirm", json=data)
        self.assertEqual(unsigned.status_code, 401)
        mismatched = {**data, "amount": 19}
        self.assertEqual((await self.post("confirm", mismatched)).status_code, 409)
        tampered = await self.client.post(
            "/internal/v1/stars/confirm", json=mismatched,
            headers=self.headers("confirm", data),
        )
        self.assertEqual(tampered.status_code, 401)
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 0)
        headers = self.headers("confirm", data)
        self.assertEqual((await self.client.post(
            "/internal/v1/stars/confirm", json=data, headers=headers,
        )).status_code, 200)
        self.assertEqual((await self.client.post(
            "/internal/v1/stars/confirm", json=data, headers=headers,
        )).status_code, 401)
        self.assertEqual((await self.post("confirm", data, owner=OWNER + 1)).status_code, 409)
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 30)
        refunded = await self.post("refund", {"charge_id": "telegram:global:42"})
        self.assertEqual(refunded.status_code, 200, refunded.text)
        self.assertTrue(refunded.json()["changed"])
        again = await self.post("refund", {"charge_id": "telegram:global:42"})
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["changed"])
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 0)
        self.assertEqual((await self.post("confirm", data)).status_code, 409)

    async def test_duplicate_charge_and_oversized_invalid_input(self):
        one = self.store.create_stars_order(OWNER, "pack_10")
        two = self.store.create_stars_order(OWNER, "pack_10")
        base = {"amount": 19, "currency": "XTR", "charge_id": "duplicate_global"}
        self.assertEqual((await self.post("confirm", {
            **base, "order_id": one["order_id"],
        })).status_code, 200)
        self.assertEqual((await self.post("confirm", {
            **base, "order_id": two["order_id"],
        })).status_code, 409)
        self.assertEqual(self.store.stars_order(OWNER, two["order_id"])["status"], "pending")
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 10)
        too_large = await self.client.post(
            "/internal/v1/stars/confirm", content=b"x" * 513,
            headers=self.headers("confirm", {
                **base, "order_id": two["order_id"],
            }),
        )
        self.assertEqual(too_large.status_code, 413)

    async def test_no_refund_without_valid_server_signed_assertion(self):
        order = self.store.create_stars_order(OWNER, "pack_10")
        self.store.record_stars_payment(OWNER, order["order_id"], "real-charge", 19, "XTR")
        self.store.fulfill_stars_order(OWNER, order["order_id"])
        payload = {"charge_id": "real-charge"}
        self.assertEqual((await self.client.post(
            "/internal/v1/stars/refund-confirm", json=payload,
        )).status_code, 401)
        self.assertEqual((await self.post("refund", payload, token="wrong-token")).status_code, 401)
        self.assertEqual((await self.post("refund", payload, owner=OWNER + 1)).status_code, 409)
        self.assertEqual(self.store.usage_snapshot(OWNER)["pack_remaining"], 10)


if __name__ == "__main__":
    unittest.main()
