"""Regression coverage for the signed, read-only Telegram bot usage profile."""
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

import main
from api import server
from api.durable_jobs import DurableJobStore
from api.internal_access import ReplayGuard, sign_access_request
from services.bot_operations import BotOperationUnavailable, fetch_bot_usage


TOKEN = "123456:TEST"
BASE = {
    "plan": "free",
    "day_utc": "2026-11-14",
    "daily_limit": 10,
    "daily_used": 3,
    "daily_remaining": 7,
    "pack_remaining": 4,
    "pro_expires_at": None,
    "enforced": True,
    "purchases_enabled": False,
}


class BotUsageClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_usage_request_returns_validated_values(self):
        with patch("services.bot_operations._call", new_callable=AsyncMock,
                   return_value=BASE.copy()) as call:
            result = await fetch_bot_usage(11, TOKEN)
        self.assertEqual((result["daily_used"], result["daily_remaining"]), (3, 7))
        call.assert_awaited_once_with(11, TOKEN, "usage", {}, "usage")

    async def test_invalid_balances_and_disabled_enforcement_fail_closed(self):
        variants = [
            {"daily_used": True},
            {"daily_limit": 100},
            {"daily_remaining": 8},
            {"pack_remaining": -1},
            {"pack_remaining": 10001},
            {"plan": "vip"},
            {"day_utc": "2026-02-30"},
            {"day_utc": "2026-2-4"},
            {"enforced": False},
            {"enforced": "true"},
            {"purchases_enabled": 1},
            {"pro_expires_at": 42},
            {"plan": "pro", "daily_limit": 100, "daily_used": 3,
             "daily_remaining": 97, "pro_expires_at": None},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                with patch("services.bot_operations._call", new_callable=AsyncMock,
                           return_value={**BASE, **changes}):
                    with self.assertRaises(BotOperationUnavailable):
                        await fetch_bot_usage(11, TOKEN)

    async def test_pro_expiry_is_validated(self):
        pro = {**BASE, "plan": "pro", "daily_limit": 100, "daily_remaining": 97,
               "pro_expires_at": time.time() + 86400}
        with patch("services.bot_operations._call", new_callable=AsyncMock,
                   return_value=pro):
            result = await fetch_bot_usage(11, TOKEN)
        self.assertEqual(result["plan"], "pro")


class BotUsageApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DurableJobStore(Path(self.tmp.name) / "jobs.sqlite3")
        self.addCleanup(self.store.close)
        self.patchers = [
            patch.object(server, "jobs", self.store),
            patch.object(server, "job_runtime", object()),
            patch.object(server, "get_settings", return_value=SimpleNamespace(bot_token=TOKEN)),
            patch.object(server, "internal_bot_operation_replay", ReplayGuard()),
            patch.object(server, "enforce_rate_limit", new_callable=AsyncMock),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.api),
            base_url="http://internal.test",
        )
        self.addAsyncCleanup(self.client.aclose)

    @staticmethod
    def headers(user_id=11, *, scope="usage"):
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        return {
            "X-FileShape-User": str(user_id),
            "X-FileShape-Time": str(timestamp),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": sign_access_request(
                TOKEN, user_id, timestamp, nonce, scope=scope
            ),
        }

    async def test_verified_owner_only_and_cache_control(self):
        self.store.reserve_operation(11, "usage:unique:operation:11111")
        route = "/internal/v1/operations/usage"
        headers = self.headers(11)
        first = await self.client.post(route, json={}, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(first.json()["daily_used"], 1)
        self.assertEqual(first.json()["daily_remaining"], 9)
        self.assertFalse(first.json()["purchases_enabled"])
        self.assertEqual((await self.client.post(route, json={}, headers=headers)).status_code, 401)
        other = await self.client.post(route, json={}, headers=self.headers(12))
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()["daily_used"], 0)

    async def test_rejects_unsigned_wrong_scope_spoofed_user_and_extra_fields(self):
        route = "/internal/v1/operations/usage"
        self.assertEqual((await self.client.post(route, json={})).status_code, 401)
        self.assertEqual((await self.client.post(route, json={},
                                                headers=self.headers(scope="reserve:tampered"))).status_code, 401)
        wrong_owner = self.headers(11)
        wrong_owner["X-FileShape-User"] = "12"
        self.assertEqual((await self.client.post(route, json={},
                                                headers=wrong_owner)).status_code, 401)
        self.assertEqual((await self.client.post(route, json={"user_id": 12},
                                                headers=self.headers())).status_code, 422)

    async def test_missing_ledger_is_unavailable_not_fabricated(self):
        with patch.object(server, "jobs", None):
            reply = await self.client.post("/internal/v1/operations/usage",
                                           json={}, headers=self.headers())
        self.assertEqual(reply.status_code, 503)


class BotUsageUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_displays_real_balances_and_disabled_checkout(self):
        with patch.object(main, "fetch_bot_usage", new_callable=AsyncMock,
                          return_value=BASE.copy()) as call:
            text = await main.usage_profile_text(11, TOKEN)
        call.assert_awaited_once_with(11, TOKEN)
        self.assertIn("3 / 10", text)
        self.assertIn("Осталось сегодня: 7", text)
        self.assertIn("Пакетные операции: 4", text)
        self.assertIn("пока недоступна", text)

    async def test_profile_hides_balance_if_api_fails(self):
        with patch.object(main, "fetch_bot_usage", new_callable=AsyncMock,
                          side_effect=BotOperationUnavailable()):
            text = await main.usage_profile_text(11, TOKEN)
        self.assertIn("Не удалось", text)
        self.assertNotIn("Осталось сегодня:", text)

    async def test_private_profile_command_uses_sender_identity(self):
        msg = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=11),
            from_user=SimpleNamespace(id=11),
            answer=AsyncMock(),
        )
        with patch.object(main, "fetch_bot_usage", new_callable=AsyncMock,
                          return_value=BASE.copy()) as fetch:
            await main.profile_message(msg, SimpleNamespace(token=TOKEN))
        fetch.assert_awaited_once_with(11, TOKEN)
        self.assertIn("3 / 10", msg.answer.call_args.args[0])
        msg.chat.id = 12
        msg.answer.reset_mock()
        with patch.object(main, "fetch_bot_usage", new_callable=AsyncMock) as fetch:
            await main.profile_message(msg, SimpleNamespace(token=TOKEN))
        fetch.assert_not_awaited()
        self.assertIn("личном чате", msg.answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
