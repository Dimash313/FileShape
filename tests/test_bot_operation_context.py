"""Bot conversions settle only after successful Telegram delivery."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import main

JOB_ID = "A" * 32
USER = 1144
TOKEN = "123456:TEST"


class MeteredBotContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_commits_once(self):
        bot = SimpleNamespace(token=TOKEN)
        with (
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=JOB_ID) as reserve,
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
        ):
            async with main.metered_bot_work(USER, bot):
                pass
        reserve.assert_awaited_once_with(USER, TOKEN)
        settle.assert_awaited_once_with(USER, TOKEN, JOB_ID, True)

    async def test_conversion_or_delivery_error_refunds(self):
        bot = SimpleNamespace(token=TOKEN)
        for failure in (ValueError("invalid input"), OSError("Telegram send failed")):
            with (
                self.subTest(error=type(failure).__name__),
                patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=JOB_ID),
                patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            ):
                with self.assertRaises(type(failure)):
                    async with main.metered_bot_work(USER, bot):
                        raise failure
                settle.assert_awaited_once_with(USER, TOKEN, JOB_ID, False)

    async def test_user_cancellation_refunds(self):
        bot = SimpleNamespace(token=TOKEN)
        with (
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
        ):
            with self.assertRaises(asyncio.CancelledError):
                async with main.metered_bot_work(USER, bot):
                    raise asyncio.CancelledError()
        settle.assert_awaited_once_with(USER, TOKEN, JOB_ID, False)

    async def test_settlement_network_uncertainty_does_not_break_completed_delivery(self):
        bot = SimpleNamespace(token=TOKEN)
        with (
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock,
                         side_effect=main.BotOperationUnavailable()) as settle,
        ):
            async with main.metered_bot_work(USER, bot):
                pass
        settle.assert_awaited_once_with(USER, TOKEN, JOB_ID, True)


if __name__ == "__main__":
    unittest.main()
