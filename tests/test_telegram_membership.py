"""Telegram membership observation service regressions."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.access_policy import AccessDecision, RequiredChannel
from api.telegram_membership import verify_memberships


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


class TelegramMembershipTests(unittest.IsolatedAsyncioTestCase):
    def channel(self, chat_id=-1001, **kwargs):
        return RequiredChannel(chat_id, NOW - timedelta(days=1), **kwargs)

    async def check(self, bot, channels=None, premium_until=None, user_id=11):
        return await verify_memberships(
            bot, user_id=user_id, channels=tuple(channels if channels is not None else [self.channel()]),
            premium_until=premium_until, now=NOW,
        )

    async def test_member_and_restricted_member(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")))
        self.assertEqual(await self.check(bot), AccessDecision.ALLOWED)
        bot.get_chat_member.return_value = SimpleNamespace(status="restricted", is_member=True)
        self.assertEqual(await self.check(bot), AccessDecision.ALLOWED)
        bot.get_chat_member.assert_awaited_with(chat_id=-1001, user_id=11)

    async def test_left_and_restricted_not_member(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="left")))
        self.assertEqual(await self.check(bot), AccessDecision.SUBSCRIPTION_REQUIRED)
        bot.get_chat_member.return_value = SimpleNamespace(status="restricted", is_member=False)
        self.assertEqual(await self.check(bot), AccessDecision.SUBSCRIPTION_REQUIRED)

    async def test_api_failure_is_not_membership(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=RuntimeError("Telegram down")))
        self.assertEqual(await self.check(bot), AccessDecision.VERIFICATION_UNAVAILABLE)

    async def test_timeout_is_not_membership(self):
        async def delayed(**_):
            await asyncio.sleep(0.1)
        bot = SimpleNamespace(get_chat_member=delayed)
        with patch("api.telegram_membership.CHECK_TIMEOUT_SECONDS", 0.001):
            self.assertEqual(await self.check(bot), AccessDecision.VERIFICATION_UNAVAILABLE)

    async def test_all_active_channels_checked(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=[
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
        ]))
        self.assertEqual(await self.check(bot, [self.channel(), self.channel(-1002)]),
                         AccessDecision.SUBSCRIPTION_REQUIRED)
        self.assertEqual(bot.get_chat_member.await_count, 2)

    async def test_premium_and_inactive_skip_telegram(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=RuntimeError("must not call")))
        self.assertEqual(await self.check(bot, premium_until=NOW + timedelta(seconds=1)),
                         AccessDecision.ALLOWED)
        self.assertEqual(await self.check(bot, [self.channel(enabled=False)]),
                         AccessDecision.ALLOWED)
        bot.get_chat_member.assert_not_awaited()

    async def test_invalid_authenticated_user_is_rejected(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock())
        for user in (0, True, -1, "11"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                await self.check(bot, user_id=user)
        bot.get_chat_member.assert_not_awaited()

    async def test_malformed_api_response_is_unavailable(self):
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status=None)))
        self.assertEqual(await self.check(bot), AccessDecision.VERIFICATION_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
