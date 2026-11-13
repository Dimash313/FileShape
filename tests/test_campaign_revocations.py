"""Campaign revocation is persistent, truthful, owner-scoped and retryable."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from api.campaign_revocations import dispatch_campaign_revocations
from api.durable_jobs import DurableJobStore


CHAT = -100123456789
LINK = "https://t.me/+Abcdefgh12345678"
USER = "a" * 64


class RevocationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "campaign.sqlite3"
        self.store = DurableJobStore(self.path)
        self.addCleanup(self.store.close)

    def make(self, *, mode="joins", target_joins=1, with_link=True):
        cid = self.store.create_campaign(
            actor_id=11, owner_id=11, chat_id=CHAT, mode=mode,
            target_joins=target_joins, starts_at=100, ends_at=200, now=100)
        if with_link:
            self.store.bind_campaign_invite(
                actor_id=11, owner_id=11, campaign_id=cid,
                invite_link=LINK, now=101)
        return cid

    def state(self, cid):
        return self.store.campaign_snapshot(
            actor_id=11, owner_id=11, campaign_id=cid)

    def start(self, cid):
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="start", now=110)

    def test_target_completion_queues_once_in_same_transaction(self):
        cid = self.make()
        self.start(cid)
        self.assertTrue(self.store.record_confirmed_join(
            campaign_id=cid, observed_invite=LINK, user_digest=USER,
            joined_at=111))
        self.assertEqual(self.state(cid)["state"], "completed")
        self.assertEqual(self.state(cid)["invite_revocation"], "pending")
        self.assertEqual(len(self.store.pending_campaign_revocations(now=112)), 1)
        self.assertFalse(self.store.record_confirmed_join(
            campaign_id=cid, observed_invite=LINK,
            user_digest="b"*64, joined_at=112))
        self.assertEqual(len(self.store.pending_campaign_revocations(now=112)), 1)
        self.assertEqual(self.state(cid)["confirmed_joins"], 1)

    def test_stop_and_expiry_enqueue_without_false_revocation(self):
        cid = self.make(mode="duration", target_joins=None)
        self.start(cid)
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="pause", now=120)
        self.assertEqual(self.state(cid)["invite_revocation"], "not_due")
        self.assertEqual(self.store.expire_campaigns(now=200), 1)
        self.assertEqual(self.store.expire_campaigns(now=201), 0)
        self.assertEqual(self.state(cid)["invite_revocation"], "pending")
        self.assertEqual(len(self.store.pending_campaign_revocations(now=201)), 1)

        self.store.record_campaign_revocation_failure(
            campaign_id=cid, chat_id=CHAT, invite_link=LINK, now=202)
        self.assertFalse(self.store.pending_campaign_revocations(now=261))
        self.assertEqual(len(self.store.pending_campaign_revocations(now=262)), 1)
        self.assertEqual(self.state(cid)["revoke_attempts"], 1)
        self.assertEqual(self.state(cid)["invite_revocation"], "pending")

        self.assertTrue(self.store.record_campaign_revoked(
            campaign_id=cid, chat_id=CHAT, invite_link=LINK, now=263))
        self.assertFalse(self.store.record_campaign_revoked(
            campaign_id=cid, chat_id=CHAT, invite_link=LINK, now=264))
        self.assertEqual(self.state(cid)["invite_revocation"], "revoked")
        self.assertEqual(self.state(cid)["revoked_at"], 263)
        self.assertFalse(self.store.pending_campaign_revocations(now=300))

    def test_stop_draft_with_no_link_cannot_queue(self):
        cid = self.make(with_link=False)
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="stop", now=110)
        self.assertEqual(self.state(cid)["invite_revocation"], "not_applicable")
        self.assertFalse(self.store.pending_campaign_revocations(now=111))

    def test_stop_bound_link_queues_and_reopen_restores(self):
        cid = self.make()
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="stop", now=110)
        self.assertEqual(self.state(cid)["invite_revocation"], "pending")
        self.store.close()
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(len(reopened.pending_campaign_revocations(now=112)), 1)
            self.assertEqual(reopened.campaign_snapshot(
                actor_id=11, owner_id=11, campaign_id=cid)["invite_revocation"], "pending")
            # Simulate a legacy terminal campaign with no outbox row.
            reopened._db.execute(
                "DELETE FROM ad_campaign_revocations WHERE campaign_id=?", (cid,))
        with DurableJobStore(self.path) as restored:
            self.assertEqual(len(restored.pending_campaign_revocations(now=112)), 1)

    def test_queue_insert_failure_rolls_back_join_and_terminal_state(self):
        cid = self.make()
        self.start(cid)
        self.store._db.execute("""
            CREATE TRIGGER reject_revocation BEFORE INSERT ON ad_campaign_revocations
            BEGIN SELECT RAISE(ABORT, 'revocation storage unavailable'); END
        """)
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.record_confirmed_join(
                campaign_id=cid, observed_invite=LINK,
                user_digest=USER, joined_at=111)
        self.assertEqual(self.state(cid)["state"], "active")
        self.assertEqual(self.state(cid)["confirmed_joins"], 0)
        self.assertEqual(self.store._db.execute(
            "SELECT count(*) FROM ad_campaign_joins WHERE campaign_id=?",
            (cid,)).fetchone()[0], 0)

    def test_revocation_updates_must_match_exact_invite_and_chat(self):
        cid = self.make()
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="stop", now=110)
        self.assertFalse(self.store.record_campaign_revoked(
            campaign_id=cid, chat_id=CHAT-1, invite_link=LINK, now=111))
        self.assertFalse(self.store.record_campaign_revocation_failure(
            campaign_id=cid, chat_id=CHAT-1, invite_link=LINK, now=111))
        self.assertEqual(self.state(cid)["invite_revocation"], "pending")


class RevocationDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self.tmp.name) / "campaign.sqlite3")
        self.cid = self.store.create_campaign(
            actor_id=11, owner_id=11, chat_id=CHAT, mode="joins",
            starts_at=100, ends_at=200, target_joins=1, now=100)
        self.store.bind_campaign_invite(
            actor_id=11, owner_id=11, campaign_id=self.cid,
            invite_link=LINK, now=101)
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=self.cid,
            action="start", now=110)
        self.store.record_confirmed_join(
            campaign_id=self.cid, observed_invite=LINK,
            user_digest=USER, joined_at=111)

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_success_only_after_real_telegram_ack(self):
        bot = SimpleNamespace(revoke_chat_invite_link=AsyncMock(return_value=True))
        self.assertEqual(await dispatch_campaign_revocations(
            self.store, bot=bot, now=112), 1)
        bot.revoke_chat_invite_link.assert_awaited_once_with(
            chat_id=CHAT, invite_link=LINK)
        self.assertEqual(await dispatch_campaign_revocations(
            self.store, bot=bot, now=113), 0)
        self.assertEqual(self.store.campaign_snapshot(
            actor_id=11, owner_id=11, campaign_id=self.cid)["invite_revocation"], "revoked")

    async def test_error_keeps_pending_and_retries_after_backoff(self):
        bot = SimpleNamespace(revoke_chat_invite_link=AsyncMock(
            side_effect=RuntimeError("Telegram unavailable")))
        self.assertEqual(await dispatch_campaign_revocations(
            self.store, bot=bot, now=112), 0)
        self.assertEqual(self.store.campaign_snapshot(
            actor_id=11, owner_id=11, campaign_id=self.cid)["invite_revocation"], "pending")
        self.assertEqual(await dispatch_campaign_revocations(
            self.store, bot=bot, now=171), 0)
        self.assertEqual(bot.revoke_chat_invite_link.await_count, 1)
        bot.revoke_chat_invite_link.side_effect = None
        self.assertEqual(await dispatch_campaign_revocations(
            self.store, bot=bot, now=172), 1)
        self.assertEqual(self.store.campaign_snapshot(
            actor_id=11, owner_id=11, campaign_id=self.cid)["invite_revocation"], "revoked")


if __name__ == "__main__":
    unittest.main()
