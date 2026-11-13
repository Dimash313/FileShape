"""Telegram campaign attribution must not count non-joins or forged links."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import ChatMemberUpdated

from services.campaign_telegram import (
    create_campaign_invite, keyed_member_digest,
    parse_confirmed_join, revoke_campaign_invite,
)

LINK = "https://t.me/+Abcdefgh12345678"


def member(status, *, member_id=123, bot=False, is_member=None):
    return SimpleNamespace(status=status, is_member=is_member,
                           user=SimpleNamespace(id=member_id, is_bot=bot))


def update(old="left", new="member", *, link=LINK, member_id=123,
           is_bot=False, chat_id=-1001234):
    return ChatMemberUpdated.model_construct(
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=42),
        date=datetime.fromtimestamp(1234567890, tz=timezone.utc),
        old_chat_member=member(old),
        new_chat_member=member(new, member_id=member_id, bot=is_bot),
        invite_link=SimpleNamespace(invite_link=link) if link else None,
    )


class TelegramCampaignEventsTests(unittest.TestCase):
    def test_real_new_member_with_exact_invite(self):
        result = parse_confirmed_join(update())
        self.assertEqual((result.chat_id, result.member_id, result.invite_link),
                         (-1001234, 123, LINK))

    def test_ignores_existing_members_promotions_leaves_and_unattributed(self):
        for event in (
            update("member", "administrator"),
            update("member", "member"),
            update("member", "left"),
            update("left", "left"),
            update(link=None),
            update(link="https://example.com/join"),
            update(is_bot=True),
            update(chat_id=123),
        ):
            with self.subTest(event=event):
                self.assertIsNone(parse_confirmed_join(event))

    def test_restricted_status_needs_actual_membership(self):
        event = update(new="restricted")
        self.assertIsNone(parse_confirmed_join(event))
        event.new_chat_member.is_member = True
        self.assertIsNotNone(parse_confirmed_join(event))

    def test_digest_is_keyed_deterministic_and_not_raw_id(self):
        digest = keyed_member_digest("secret", 123)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, keyed_member_digest("secret", 123))
        self.assertNotEqual(digest, keyed_member_digest("other", 123))
        self.assertNotEqual(digest, keyed_member_digest("secret", 124))
        for bad in (0, -1, True, "123"):
            with self.assertRaises(ValueError):
                keyed_member_digest("secret", bad)
        with self.assertRaises(ValueError):
            keyed_member_digest("", 123)


class TelegramCampaignInviteTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_and_revoke_link(self):
        bot = SimpleNamespace(
            create_chat_invite_link=AsyncMock(return_value=SimpleNamespace(invite_link=LINK)),
            revoke_chat_invite_link=AsyncMock(return_value=True),
        )
        campaign_id = "abcdefghijklmnopqrstuvwx"
        self.assertEqual(await create_campaign_invite(bot, chat_id=-1001234,
                                                      campaign_id=campaign_id), LINK)
        bot.create_chat_invite_link.assert_awaited_once_with(
            chat_id=-1001234, name="FileShape " + campaign_id,
            creates_join_request=False)
        await revoke_campaign_invite(bot, chat_id=-1001234, invite_link=LINK)
        bot.revoke_chat_invite_link.assert_awaited_once_with(
            chat_id=-1001234, invite_link=LINK)

    async def test_revoke_requires_explicit_telegram_acknowledgement(self):
        bot = SimpleNamespace(revoke_chat_invite_link=AsyncMock(return_value=False))
        with self.assertRaises(RuntimeError):
            await revoke_campaign_invite(bot, chat_id=-1001234, invite_link=LINK)

    async def test_telegram_errors_propagate_without_fake_links(self):
        bot = SimpleNamespace(create_chat_invite_link=AsyncMock(side_effect=RuntimeError("forbidden")))
        with self.assertRaises(RuntimeError):
            await create_campaign_invite(bot, chat_id=-1001234,
                                         campaign_id="abcdefghijklmnop")

    async def test_invalid_input_cannot_reach_telegram(self):
        bot = SimpleNamespace(create_chat_invite_link=AsyncMock(),
                              revoke_chat_invite_link=AsyncMock())
        with self.assertRaises(ValueError):
            await create_campaign_invite(bot, chat_id=123, campaign_id="abcdefghijklmnop")
        with self.assertRaises(ValueError):
            await create_campaign_invite(bot, chat_id=-1001234, campaign_id="bad")
        with self.assertRaises(ValueError):
            await revoke_campaign_invite(bot, chat_id=-1001234, invite_link="https://fake")
        bot.create_chat_invite_link.assert_not_awaited()
        bot.revoke_chat_invite_link.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
