"""Authoritative Telegram transaction-history recovery for lost Stars updates."""
from types import SimpleNamespace as S
import unittest
from unittest.mock import AsyncMock, patch

from services.stars_bridge import StarsBridgeUnavailable
from services.stars_reconciliation import (
    _incoming_invoice, _outgoing_invoice_refund, reconcile_star_transactions,
)

OWNER = 34567
ORDER = "a" * 32
NOW = 1800000000


def transaction(*, order=ORDER, buyer=OWNER, amount=19, charge="telegram_charge_1",
                paid_at=NOW - 10, kind="invoice_payment", source_type="user",
                refund=False, nanostars=None):
    source = S(
        type=source_type, transaction_type=kind,
        user=S(id=buyer), invoice_payload="fileshape:" + order,
    )
    return S(
        id=charge, amount=amount, nanostar_amount=nanostars,
        date=paid_at, source=None if refund else source,
        receiver=S(type="user", user=S(id=buyer)) if refund else None,
    )


class TransactionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = S(
            token="123456:TEST", get_star_transactions=AsyncMock(
                return_value=S(transactions=[]),
            ),
        )

    async def test_recovers_telegram_confirmed_invoice_with_verified_fields(self):
        self.bot.get_star_transactions.return_value = S(transactions=[
            transaction(charge="paid_invoice_1"),
        ])
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock, return_value={"status": "fulfilled"},
        ) as receipt:
            result = await reconcile_star_transactions(self.bot, now=NOW)
        receipt.assert_awaited_once_with(
            OWNER, self.bot.token, ORDER, 19, "XTR", "paid_invoice_1",
        )
        self.assertEqual(result, {
            "scanned": 1, "matched": 1, "confirmed": 1,
            "failed": 0, "refunded": 0, "refund_failed": 0, "complete": True,
        })
        self.bot.get_star_transactions.assert_awaited_once_with(
            offset=0, limit=100, request_timeout=20,
        )

    async def test_only_real_inbound_invoice_payment_is_reconciled(self):
        entries = [
            transaction(kind="paid_media_payment"),
            transaction(source_type="other"),
            transaction(amount=-19),
            transaction(refund=True),
            transaction(amount=0),
            transaction(buyer=True),
            transaction(buyer=0),
            transaction(order="bad-id"),
            transaction(nanostars=1),
            transaction(paid_at=NOW - 31 * 86400),
            transaction(paid_at=NOW + 300),
        ]
        self.bot.get_star_transactions.return_value = S(transactions=entries)
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock,
        ) as receipt:
            result = await reconcile_star_transactions(self.bot, now=NOW)
        receipt.assert_not_awaited()
        self.assertEqual(result["scanned"], len(entries))
        self.assertEqual(result["matched"], 0)
        self.assertTrue(result["complete"])

    async def test_telegram_outgoing_refund_is_reconciled_without_any_new_grant(self):
        refund = transaction(refund=True, amount=-19, charge="original_invoice_charge")
        refund.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(transactions=[refund])
        with (
            patch("services.stars_reconciliation.confirm_stars_payment", new_callable=AsyncMock) as paid,
            patch("services.stars_reconciliation.confirm_stars_refund",
                  new_callable=AsyncMock, return_value={"status": "refunded"}) as refunded,
        ):
            outcome = await reconcile_star_transactions(self.bot, now=NOW)
        paid.assert_not_awaited()
        refunded.assert_awaited_once_with(OWNER, self.bot.token, "original_invoice_charge")
        self.assertEqual(outcome["refunded"], 1)
        self.assertEqual(outcome["refund_failed"], 0)
        self.assertEqual(outcome["confirmed"], 0)

    async def test_failed_refund_api_delivery_is_not_claimed_successful(self):
        refund = transaction(refund=True, amount=-19, charge="original_invoice_charge")
        refund.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(transactions=[refund])
        with patch(
            "services.stars_reconciliation.confirm_stars_refund",
            new_callable=AsyncMock, side_effect=StarsBridgeUnavailable("API offline"),
        ):
            outcome = await reconcile_star_transactions(self.bot, now=NOW)
        self.assertEqual(outcome["refund_failed"], 1)
        self.assertEqual(outcome["refunded"], 0)

    def test_only_negative_outgoing_invoice_refunds_are_considered(self):
        refund = transaction(refund=True, amount=-19)
        refund.receiver.transaction_type = "invoice_payment"
        self.assertEqual(_outgoing_invoice_refund(refund), (OWNER, "telegram_charge_1", 19, NOW - 10))
        other = transaction(refund=True, amount=-19)
        other.receiver.transaction_type = "paid_media_payment"
        self.assertIsNone(_outgoing_invoice_refund(other))
        other = transaction(refund=True, amount=19)
        other.receiver.transaction_type = "invoice_payment"
        self.assertIsNone(_outgoing_invoice_refund(other))
        other = transaction(refund=True, amount=-19)
        other.receiver.transaction_type = "invoice_payment"
        other.receiver.invoice_payload = "other-product"
        self.assertIsNone(_outgoing_invoice_refund(other))

    async def test_multi_page_recovery_uses_offset_and_no_sort_direction_guess(self):
        transactions = [
            transaction(charge=f"wrong_{i}", kind="paid_media_payment")
            for i in range(100)
        ]
        transactions.append(transaction(charge="next_page"))
        self.bot.get_star_transactions.side_effect = [
            S(transactions=transactions[:100]),
            S(transactions=transactions[100:]),
        ]
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock,
        ) as receipt:
            result = await reconcile_star_transactions(self.bot, now=NOW)
        receipt.assert_awaited_once()
        self.assertEqual(result["scanned"], 101)
        self.assertTrue(result["complete"])
        self.assertEqual(self.bot.get_star_transactions.await_args_list[1].kwargs["offset"], 100)

    async def test_refund_is_processed_before_paid_receipt_regardless_of_page_order(self):
        paid = transaction(charge="same_charge", amount=19)
        refunded = transaction(charge="same_charge", refund=True, amount=-19)
        refunded.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(
            transactions=[paid, refunded],
        )
        with (
            patch("services.stars_reconciliation.confirm_stars_payment",
                  new_callable=AsyncMock) as confirm,
            patch("services.stars_reconciliation.confirm_stars_paid_and_refunded",
                  new_callable=AsyncMock, return_value={"status": "refunded"}) as refund,
        ):
            outcome = await reconcile_star_transactions(self.bot, now=NOW)
        confirm.assert_not_awaited()
        refund.assert_awaited_once_with(OWNER, self.bot.token, ORDER, 19, "XTR", "same_charge")
        self.assertEqual(outcome["matched"], 1)
        self.assertEqual(outcome["refunded"], 1)
        self.assertEqual(outcome["confirmed"], 0)

    async def test_acknowledgement_cache_skips_replay_until_bot_restart(self):
        charge = transaction(charge="cached_charge")
        self.bot.get_star_transactions.return_value = S(transactions=[charge])
        cache = set()
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock,
        ) as confirm:
            first = await reconcile_star_transactions(
                self.bot, now=NOW, acknowledged_charges=cache,
            )
            second = await reconcile_star_transactions(
                self.bot, now=NOW, acknowledged_charges=cache,
            )
        confirm.assert_awaited_once()
        self.assertEqual(cache, {"paid:cached_charge"})
        self.assertEqual(first["confirmed"], 1)
        self.assertEqual(second["confirmed"], 0)

    async def test_refund_api_failure_still_suppresses_its_paid_receipt(self):
        paid = transaction(charge="same_charge")
        refunded = transaction(charge="same_charge", refund=True, amount=-19)
        refunded.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(transactions=[paid, refunded])
        with (
            patch("services.stars_reconciliation.confirm_stars_payment",
                  new_callable=AsyncMock) as paid_confirm,
            patch("services.stars_reconciliation.confirm_stars_paid_and_refunded",
                  new_callable=AsyncMock, side_effect=StarsBridgeUnavailable()) as refund_confirm,
        ):
            outcome = await reconcile_star_transactions(self.bot, now=NOW)
        paid_confirm.assert_not_awaited()
        refund_confirm.assert_awaited_once()
        self.assertEqual(outcome["refund_failed"], 1)
        self.assertEqual(outcome["confirmed"], 0)

    async def test_refund_processed_even_when_payment_is_previously_cached(self):
        paid = transaction(charge="later_refund")
        returned = transaction(charge="later_refund", refund=True, amount=-19)
        returned.receiver.transaction_type = "invoice_payment"
        cache = {"paid:later_refund"}
        self.bot.get_star_transactions.return_value = S(transactions=[paid, returned])
        with (
            patch("services.stars_reconciliation.confirm_stars_payment",
                  new_callable=AsyncMock) as grant,
            patch("services.stars_reconciliation.confirm_stars_paid_and_refunded",
                  new_callable=AsyncMock, return_value={"status": "refunded"}) as refund,
        ):
            result = await reconcile_star_transactions(
                self.bot, now=NOW, acknowledged_charges=cache,
            )
        grant.assert_not_awaited()
        refund.assert_awaited_once()
        self.assertIn("refund:later_refund", cache)
        self.assertEqual(result["refunded"], 1)

    async def test_mismatched_refund_amount_never_grants_or_marks_order(self):
        paid = transaction(charge="mismatch_amount", amount=19)
        returned = transaction(charge="mismatch_amount", refund=True, amount=-10)
        returned.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(transactions=[paid, returned])
        with (
            patch("services.stars_reconciliation.confirm_stars_payment",
                  new_callable=AsyncMock) as grant,
            patch("services.stars_reconciliation.confirm_stars_paid_and_refunded",
                  new_callable=AsyncMock) as refund,
        ):
            outcome = await reconcile_star_transactions(self.bot, now=NOW)
        grant.assert_not_awaited()
        refund.assert_not_awaited()
        self.assertEqual(outcome["refund_failed"], 1)

    async def test_failed_internal_api_does_not_claim_complete_reconciliation(self):
        self.bot.get_star_transactions.return_value = S(transactions=[
            transaction(charge="missing_delivery"),
        ])
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock, side_effect=StarsBridgeUnavailable("API offline"),
        ):
            result = await reconcile_star_transactions(self.bot, now=NOW)
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["matched"], 1)
        # History traversal can finish while payment settlement remains pending.
        self.assertTrue(result["complete"])

    async def test_hard_page_limit_is_honestly_reported_as_truncated(self):
        self.bot.get_star_transactions.side_effect = [
            S(transactions=[transaction(kind="paid_media_payment") for _ in range(100)]),
            S(transactions=[transaction(kind="paid_media_payment") for _ in range(100)]),
        ]
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock,
        ) as receipt:
            result = await reconcile_star_transactions(
                self.bot, now=NOW, max_pages=2,
            )
        self.assertEqual(result["scanned"], 200)
        self.assertFalse(result["complete"])
        receipt.assert_not_awaited()

    async def test_truncated_history_never_grants_when_refund_may_be_unseen(self):
        # A payment appears on the first page; its refund might be on the
        # next page, beyond this bounded scan. Do not grant prematurely.
        paid = transaction(charge="unseen_refund_risk")
        self.bot.get_star_transactions.return_value = S(
            transactions=[paid] + [
                transaction(kind="paid_media_payment", charge=f"filler_{i}")
                for i in range(99)
            ],
        )
        with patch(
            "services.stars_reconciliation.confirm_stars_payment",
            new_callable=AsyncMock,
        ) as grant:
            result = await reconcile_star_transactions(
                self.bot, now=NOW, max_pages=1,
            )
        grant.assert_not_awaited()
        self.assertFalse(result["complete"])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["confirmed"], 0)

    async def test_truncated_history_can_still_reconcile_verified_refunds(self):
        returned = transaction(charge="refund_on_first_page", refund=True, amount=-19)
        returned.receiver.transaction_type = "invoice_payment"
        self.bot.get_star_transactions.return_value = S(
            transactions=[returned] + [
                transaction(kind="paid_media_payment", charge=f"filler_{i}")
                for i in range(99)
            ],
        )
        with (
            patch("services.stars_reconciliation.confirm_stars_refund",
                  new_callable=AsyncMock, return_value={"status": "refunded"}) as refund,
            patch("services.stars_reconciliation.confirm_stars_payment",
                  new_callable=AsyncMock) as grant,
        ):
            result = await reconcile_star_transactions(self.bot, now=NOW, max_pages=1)
        refund.assert_awaited_once_with(
            OWNER, self.bot.token, "refund_on_first_page",
        )
        grant.assert_not_awaited()
        self.assertFalse(result["complete"])
        self.assertEqual(result["refunded"], 1)

    async def test_invalid_bot_api_response_fails_closed(self):
        self.bot.get_star_transactions.return_value = S(transactions=None)
        with self.assertRaises(StarsBridgeUnavailable):
            await reconcile_star_transactions(self.bot, now=NOW)
        self.bot.get_star_transactions.return_value = S(transactions=[None] * 101)
        with self.assertRaises(StarsBridgeUnavailable):
            await reconcile_star_transactions(self.bot, now=NOW)

    async def test_bounded_reconciliation_rejects_unsafe_parameters(self):
        for opts in (
            {"now": False}, {"now": 0}, {"lookback_seconds": 0},
            {"max_pages": 0}, {"max_pages": True}, {"max_pages": 21},
        ):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                await reconcile_star_transactions(self.bot, **opts)
        self.bot.get_star_transactions.assert_not_awaited()

    def test_refunds_or_unsigned_payloads_are_not_payment_proof(self):
        self.assertIsNone(_incoming_invoice(transaction(refund=True)))
        invalid = transaction()
        invalid.source.invoice_payload = "random:payload"
        self.assertIsNone(_incoming_invoice(invalid))
        invalid = transaction()
        invalid.source.user = None
        self.assertIsNone(_incoming_invoice(invalid))


if __name__ == "__main__":
    unittest.main()
