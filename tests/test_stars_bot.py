"""Stars bot handlers: signed order checkout, receipt-only delivery, no bypass."""
from datetime import datetime, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.types import CallbackQuery, Chat, Message, User

import main

OWNER = 13579
TOKEN = "123456:TEST"
ORDER = "a" * 32
CHARGE = "charge:telegram:001"


class StarsBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = User(id=OWNER, first_name="Buyer", is_bot=False)
        self.chat = Chat(id=OWNER, type="private")
        self.bot = SimpleNamespace(token=TOKEN)
        self.message = Message(
            message_id=1, date=datetime.now(timezone.utc), chat=self.chat,
            from_user=self.actor, text="Buy",
        )

    async def test_disabled_checkout_never_sends_an_invoice(self):
        with (
            patch.object(main, "checkout_enabled", return_value=False),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as quote,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            callback = SimpleNamespace(
                data="buy:pack_10", message=self.message,
                from_user=self.actor, answer=AsyncMock(),
            )
            await main.buy_stars_product(callback, self.bot)
            quote.assert_not_awaited()
            invoice.assert_not_awaited()
            callback.answer.assert_awaited_once()
            self.assertTrue(callback.answer.call_args.kwargs["show_alert"])

    async def test_invoice_uses_only_server_quote_and_single_xtr_price(self):
        quote = {
            "order_id": ORDER, "sku": "pack_10", "amount": 19,
            "currency": "XTR", "status": "pending",
        }
        callback = SimpleNamespace(
            data="buy:pack_10", message=self.message,
            from_user=self.actor, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock,
                         return_value=quote) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            await main.buy_stars_product(callback, self.bot)
        create.assert_awaited_once_with(OWNER, TOKEN, "pack_10")
        invoice.assert_awaited_once()
        args = invoice.call_args.kwargs
        self.assertEqual(args["payload"], "fileshape:" + ORDER)
        self.assertEqual(args["currency"], "XTR")
        self.assertEqual(len(args["prices"]), 1)
        self.assertEqual(args["prices"][0].amount, 19)

    async def test_price_mismatch_cannot_send_invoice(self):
        callback = SimpleNamespace(
            data="buy:pack_10", message=self.message,
            from_user=self.actor, answer=AsyncMock(),
        )
        quote = {
            "order_id": ORDER, "sku": "pack_10", "amount": 149,
            "currency": "XTR", "status": "pending",
        }
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock,
                         return_value=quote),
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
        ):
            await main.buy_stars_product(callback, self.bot)
        invoice.assert_not_awaited()
        self.assertIn("недоступен", answer.call_args.args[0])

    async def test_precheckout_denies_when_disabled_or_unverifiable(self):
        query = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER,
            from_user=self.actor, total_amount=19, currency="XTR",
            answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=False),
            patch.object(main, "approve_stars_checkout", new_callable=AsyncMock) as approve,
        ):
            await main.stars_precheckout(query, self.bot)
            self.assertFalse(query.answer.call_args.kwargs["ok"])
            approve.assert_not_awaited()
        query.answer.reset_mock()
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "approve_stars_checkout", new_callable=AsyncMock,
                         side_effect=main.StarsBridgeUnavailable()) as approve,
        ):
            await main.stars_precheckout(query, self.bot)
            approve.assert_awaited_once_with(OWNER, TOKEN, ORDER, 19, "XTR")
            self.assertFalse(query.answer.call_args.kwargs["ok"])

    async def test_precheckout_approves_only_verified_order(self):
        query = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER,
            from_user=self.actor, total_amount=19, currency="XTR",
            answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "approve_stars_checkout", new_callable=AsyncMock, return_value=True),
        ):
            await main.stars_precheckout(query, self.bot)
            query.answer.assert_awaited_once_with(ok=True, error_message=None)

    async def test_successful_payment_routes_to_api_even_if_sales_disabled(self):
        payment = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER, currency="XTR",
            total_amount=19, telegram_payment_charge_id=CHARGE,
        )
        message = SimpleNamespace(
            successful_payment=payment, from_user=self.actor,
            chat=self.chat, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=False),
            patch.object(main, "confirm_stars_payment", new_callable=AsyncMock,
                         return_value={"order_id": ORDER, "status": "fulfilled", "created": True}) as confirm,
        ):
            await main.stars_payment_received(message, self.bot)
        confirm.assert_awaited_once_with(OWNER, TOKEN, ORDER, 19, "XTR", CHARGE)
        self.assertIn("подтверждена", message.answer.call_args.args[0])

    async def test_payment_bridge_outage_does_not_pretend_to_fulfill(self):
        payment = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER, currency="XTR",
            total_amount=19, telegram_payment_charge_id=CHARGE,
        )
        message = SimpleNamespace(
            successful_payment=payment, from_user=self.actor,
            chat=self.chat, answer=AsyncMock(),
        )
        with patch.object(
            main, "confirm_stars_payment", new_callable=AsyncMock,
            side_effect=main.StarsBridgeUnavailable(),
        ):
            await main.stars_payment_received(message, self.bot)
        self.assertIn("пока не завершено", message.answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
