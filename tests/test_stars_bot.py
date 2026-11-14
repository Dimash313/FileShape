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

    async def test_tariff_selection_shows_terms_without_creating_invoice(self):
        callback = SimpleNamespace(
            data="buy:pack_10", message=self.message,
            from_user=self.actor, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
            patch.object(Message, "answer", new_callable=AsyncMock) as reply,
        ):
            await main.buy_stars_product(callback, self.bot)
        create.assert_not_awaited()
        invoice.assert_not_awaited()
        reply.assert_awaited_once()
        self.assertIn("Условия покупки", reply.call_args.args[0])
        terms_button = reply.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(
            terms_button.callback_data,
            f"buy:agree:{main.STARS_TERMS_VERSION}:pack_10",
        )

    async def test_agreement_uses_only_server_quote_and_single_xtr_price(self):
        quote = {
            "order_id": ORDER, "sku": "pack_10", "amount": 19,
            "currency": "XTR", "status": "pending",
        }
        callback = SimpleNamespace(
            data=f"buy:agree:{main.STARS_TERMS_VERSION}:pack_10",
            message=self.message, from_user=self.actor, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock,
                         return_value=quote) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            await main.buy_stars_after_terms(callback, self.bot)
        create.assert_awaited_once_with(OWNER, TOKEN, "pack_10")
        invoice.assert_awaited_once()
        args = invoice.call_args.kwargs
        self.assertEqual(args["payload"], "fileshape:" + ORDER)
        self.assertEqual(args["currency"], "XTR")
        self.assertEqual(len(args["prices"]), 1)
        self.assertEqual(args["prices"][0].amount, 19)

    async def test_wrong_price_after_agreement_cannot_send_invoice(self):
        callback = SimpleNamespace(
            data=f"buy:agree:{main.STARS_TERMS_VERSION}:pack_10",
            message=self.message, from_user=self.actor, answer=AsyncMock(),
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
            await main.buy_stars_after_terms(callback, self.bot)
        invoice.assert_not_awaited()
        self.assertIn("недоступен", answer.call_args.args[0])

    async def test_stale_terms_and_invalid_agreement_never_create_order(self):
        callbacks = (
            "buy:agree:old:pack_10",
            "buy:agree:" + main.STARS_TERMS_VERSION + ":unknown",
            "buy:agree:" + main.STARS_TERMS_VERSION + ":pack_10:extra",
            "buy:agree:" + main.STARS_TERMS_VERSION,
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            for data in callbacks:
                callback = SimpleNamespace(
                    data=data, message=self.message,
                    from_user=self.actor, answer=AsyncMock(),
                )
                await main.buy_stars_after_terms(callback, self.bot)
                self.assertTrue(callback.answer.call_args.kwargs["show_alert"])
        create.assert_not_awaited()
        invoice.assert_not_awaited()

    async def test_agreement_rejected_outside_own_private_chat(self):
        outsider = User(id=OWNER + 1, first_name="Other", is_bot=False)
        callback = SimpleNamespace(
            data=f"buy:agree:{main.STARS_TERMS_VERSION}:pack_10",
            message=self.message, from_user=outsider, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            await main.buy_stars_after_terms(callback, self.bot)
        callback.answer.assert_awaited_once()
        self.assertTrue(callback.answer.call_args.kwargs["show_alert"])
        create.assert_not_awaited()
        invoice.assert_not_awaited()

    async def test_all_catalog_prices_are_visible_before_explicit_consent(self):
        with (
            patch.object(main, "checkout_enabled", return_value=True),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as create,
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
        ):
            for sku, (title, _, amount) in main.STARS_SKUS.items():
                callback = SimpleNamespace(
                    data="buy:" + sku, message=self.message,
                    from_user=self.actor, answer=AsyncMock(),
                )
                await main.buy_stars_product(callback, self.bot)
                content = answer.call_args.args[0]
                self.assertIn(title, content)
                self.assertIn(str(amount), content)
                self.assertIn("Условия покупки", content)
                buttons = answer.call_args.kwargs["reply_markup"].inline_keyboard
                self.assertEqual(
                    buttons[0][0].callback_data,
                    f"buy:agree:{main.STARS_TERMS_VERSION}:{sku}",
                )
        create.assert_not_awaited()

    async def test_checkout_flag_switch_off_after_terms_prevents_invoice(self):
        callback = SimpleNamespace(
            data=f"buy:agree:{main.STARS_TERMS_VERSION}:pack_10",
            message=self.message, from_user=self.actor, answer=AsyncMock(),
        )
        with (
            patch.object(main, "checkout_enabled", return_value=False),
            patch.object(main, "create_stars_quote", new_callable=AsyncMock) as create,
            patch.object(Message, "answer_invoice", new_callable=AsyncMock) as invoice,
        ):
            await main.buy_stars_after_terms(callback, self.bot)
        self.assertTrue(callback.answer.call_args.kwargs["show_alert"])
        create.assert_not_awaited()
        invoice.assert_not_awaited()

    async def test_terms_command_displays_current_version_without_checkout(self):
        with (
            patch.object(main, "checkout_enabled", return_value=False),
            patch.object(Message, "answer", new_callable=AsyncMock) as answer,
        ):
            await main.terms_message(self.message)
        answer.assert_awaited_once()
        self.assertIn("Условия покупки", answer.call_args.args[0])
        self.assertIn(main.STARS_TERMS_VERSION, answer.call_args.args[0])
        self.assertIn("/paysupport", answer.call_args.args[0])

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

    async def test_telegram_refund_service_event_reconciles_buyer_entitlement(self):
        refund = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER, total_amount=19,
            currency="XTR", telegram_payment_charge_id=CHARGE,
        )
        message = SimpleNamespace(refunded_payment=refund, chat=self.chat, answer=AsyncMock())
        with patch.object(
            main, "confirm_stars_refund", new_callable=AsyncMock,
            return_value={"status": "refunded", "changed": True},
        ) as reconcile:
            await main.stars_refund_received(message, self.bot)
        reconcile.assert_awaited_once_with(OWNER, TOKEN, CHARGE)
        self.assertIn("Возврат", message.answer.call_args.args[0])

    async def test_refund_unrelated_invoice_is_rejected_before_api_access(self):
        for payload in ("not-fileshape", "fileshape:abc", "other:" + ORDER):
            with self.subTest(payload=payload):
                refund = SimpleNamespace(
                    invoice_payload=payload, total_amount=19,
                    currency="XTR", telegram_payment_charge_id=CHARGE,
                )
                message = SimpleNamespace(
                    refunded_payment=refund, chat=self.chat, answer=AsyncMock(),
                )
                with patch.object(
                    main, "confirm_stars_refund", new_callable=AsyncMock,
                ) as bridge:
                    await main.stars_refund_received(message, self.bot)
                bridge.assert_not_awaited()
                message.answer.assert_not_awaited()

    async def test_telegram_refund_bridge_outage_does_not_falsely_acknowledge(self):
        refund = SimpleNamespace(
            invoice_payload="fileshape:" + ORDER, total_amount=19,
            currency="XTR", telegram_payment_charge_id=CHARGE,
        )
        message = SimpleNamespace(refunded_payment=refund, chat=self.chat, answer=AsyncMock())
        with patch.object(
            main, "confirm_stars_refund", new_callable=AsyncMock,
            side_effect=main.StarsBridgeUnavailable(),
        ):
            await main.stars_refund_received(message, self.bot)
        message.answer.assert_not_awaited()

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
