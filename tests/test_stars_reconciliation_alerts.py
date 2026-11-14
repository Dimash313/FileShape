"""Owner-only Stars reconciliation alerts are bounded and contain no buyer data."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from services.stars_reconciliation import (
    ReconciliationAlert, _owner_alert_chat, star_reconciliation_loop,
)

OWNER = 12345678


class OwnerReconciliationAlertsTests(unittest.IsolatedAsyncioTestCase):
    def bot(self):
        return SimpleNamespace(send_message=AsyncMock())

    def env(self, owner=str(OWNER)):
        return patch.dict(os.environ, {"FILESHAPE_OWNER_ID": owner})

    async def test_only_configured_valid_owner_can_receive_alerts(self):
        for value in ("", "0", "-1", "not_a_number", "9999999999999999999999999"):
            with self.subTest(value=value), self.env(value):
                self.assertIsNone(_owner_alert_chat())
                bot = self.bot()
                self.assertFalse(await ReconciliationAlert().send(bot, "billing warning", now=1))
                bot.send_message.assert_not_awaited()
        with self.env():
            self.assertEqual(_owner_alert_chat(), OWNER)

    async def test_throttles_duplicate_incidents_and_omits_sensitive_data(self):
        bot = self.bot()
        alert = ReconciliationAlert(cooldown_seconds=120)
        text = "Stars reconciliation: 1 unconfirmed payment"
        with self.env():
            self.assertTrue(await alert.send(bot, text, now=1))
            self.assertFalse(await alert.send(bot, text, now=2))
            self.assertFalse(await alert.send(bot, text, now=120))
            self.assertTrue(await alert.send(bot, text, now=121))
        self.assertEqual(bot.send_message.await_count, 2)
        for call in bot.send_message.call_args_list:
            self.assertEqual(call.kwargs["chat_id"], OWNER)
            self.assertEqual(call.kwargs["text"], text)

    async def test_bad_alert_never_floods_and_network_errors_do_not_raise(self):
        bot = self.bot()
        bot.send_message.side_effect = OSError("network unavailable")
        alert = ReconciliationAlert(cooldown_seconds=1800)
        with self.env():
            self.assertFalse(await alert.send(bot, "billing warning", now=100))
            self.assertFalse(await alert.send(bot, "billing warning", now=101))
            self.assertFalse(await alert.send(bot, "x" * 401, now=5000))
        bot.send_message.assert_awaited_once_with(chat_id=OWNER, text="billing warning")

    async def test_history_scan_timeout_notifies_operator_and_never_hangs(self):
        import asyncio

        bot = self.bot()
        started = asyncio.Event()

        async def hangs(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        with (
            self.env(),
            patch("services.stars_reconciliation.MAX_SCAN_WALL_SECONDS", 0.01),
            patch("services.stars_reconciliation.reconcile_star_transactions",
                  side_effect=hangs),
            patch("services.stars_reconciliation.asyncio.sleep",
                  new_callable=AsyncMock, side_effect=asyncio.CancelledError()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await star_reconciliation_loop(bot)
        self.assertTrue(started.is_set())
        bot.send_message.assert_awaited_once()
        self.assertIn("история Telegram недоступна",
                      bot.send_message.call_args.kwargs["text"])

    async def test_incomplete_scan_triggers_owner_notification(self):
        bot = self.bot()
        outcome = {
            "complete": False, "failed": 2, "refund_failed": 1,
            "scanned": 1000, "matched": 3,
        }
        with (
            self.env(),
            patch("services.stars_reconciliation.reconcile_star_transactions",
                  new_callable=AsyncMock, return_value=outcome),
            patch("services.stars_reconciliation.asyncio.sleep",
                  new_callable=AsyncMock, side_effect=__import__("asyncio").CancelledError()),
        ):
            with self.assertRaises(__import__("asyncio").CancelledError):
                await star_reconciliation_loop(bot)
        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.call_args.kwargs["chat_id"], OWNER)
        self.assertIn("неполная", bot.send_message.call_args.kwargs["text"])
        self.assertNotIn("charge_id", bot.send_message.call_args.kwargs["text"])


if __name__ == "__main__":
    unittest.main()
