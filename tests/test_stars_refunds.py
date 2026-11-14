"""Never reverse Stars value unless Telegram confirmed and actor is owner."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from services.stars_bridge import StarsBridgeUnavailable
from services.stars_refunds import (
    StarsRefundReconciliationRequired, refund_stars_verified,
)

OWNER = 10101
BUYER = 20202
TOKEN = "123456:TEST"


class StarsRefundPrimitiveTests(unittest.IsolatedAsyncioTestCase):
    def bot(self, value=True, exception=None):
        fn = AsyncMock(return_value=value)
        if exception is not None:
            fn.side_effect = exception
        return SimpleNamespace(refund_star_payment=fn, token=TOKEN)

    async def test_owner_only_and_no_network_for_untrusted_actor(self):
        bot = self.bot()
        with patch.dict(os.environ, {"FILESHAPE_OWNER_ID": str(OWNER)}):
            for actor in (0, BUYER, True, "10101"):
                with self.subTest(actor=actor), self.assertRaises(PermissionError):
                    await refund_stars_verified(
                        bot, actor_id=actor, buyer_id=BUYER, telegram_charge_id="charge01",
                    )
        bot.refund_star_payment.assert_not_awaited()

    async def test_telegram_confirmation_precedes_signed_ledger_refund(self):
        bot = self.bot()
        with (
            patch.dict(os.environ, {"FILESHAPE_OWNER_ID": str(OWNER)}),
            patch("services.stars_refunds.confirm_stars_refund", new_callable=AsyncMock,
                  return_value={"status": "refunded", "changed": True}) as ledger,
        ):
            result = await refund_stars_verified(
                bot, actor_id=OWNER, buyer_id=BUYER, telegram_charge_id="charge01",
            )
        self.assertTrue(result["changed"])
        bot.refund_star_payment.assert_awaited_once_with(
            user_id=BUYER, telegram_payment_charge_id="charge01",
        )
        ledger.assert_awaited_once_with(BUYER, TOKEN, "charge01")

    async def test_failed_telegram_refund_does_not_revoke_granted_value(self):
        for bot in (self.bot(False), self.bot(exception=OSError("Telegram unavailable"))):
            with (
                patch.dict(os.environ, {"FILESHAPE_OWNER_ID": str(OWNER)}),
                patch("services.stars_refunds.confirm_stars_refund", new_callable=AsyncMock) as ledger,
            ):
                with self.assertRaises((RuntimeError, OSError)):
                    await refund_stars_verified(
                        bot, actor_id=OWNER, buyer_id=BUYER, telegram_charge_id="charge01",
                    )
                ledger.assert_not_awaited()

    async def test_telegram_success_with_api_outage_reports_reconciliation(self):
        bot = self.bot()
        with (
            patch.dict(os.environ, {"FILESHAPE_OWNER_ID": str(OWNER)}),
            patch("services.stars_refunds.confirm_stars_refund", new_callable=AsyncMock,
                  side_effect=StarsBridgeUnavailable()),
        ):
            with self.assertRaises(StarsRefundReconciliationRequired):
                await refund_stars_verified(
                    bot, actor_id=OWNER, buyer_id=BUYER, telegram_charge_id="charge01",
                )


if __name__ == "__main__":
    unittest.main()
