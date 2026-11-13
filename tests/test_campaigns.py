"""Ad campaign ledger: owner control, dedup, lifecycle and durability."""
import tempfile
import unittest
from pathlib import Path

from api.durable_jobs import DurableJobStore


LINK = "https://t.me/+Abcdefgh12345678"
LINK2 = "https://t.me/+OtherLink1234567"
USER = "a" * 64


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "campaign.sqlite3"
        self.store = DurableJobStore(self.path)
        self.addCleanup(self.store.close)

    def make(self, **kwargs):
        params = dict(actor_id=11, owner_id=11, chat_id=-100123456789,
                      mode="joins", target_joins=2, starts_at=100, ends_at=200, now=100)
        params.update(kwargs)
        return self.store.create_campaign(**params)

    def start(self, campaign_id, *, now=110):
        self.store.bind_campaign_invite(actor_id=11, owner_id=11,
                                        campaign_id=campaign_id, invite_link=LINK, now=101)
        return self.store.change_campaign_state(actor_id=11, owner_id=11,
                                                campaign_id=campaign_id, action="start", now=now)

    def test_two_verified_joins_stop_exactly_at_target_and_deduplicate(self):
        campaign = self.make()
        self.assertEqual(self.start(campaign), "active")
        self.assertTrue(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest=USER, observed_invite=LINK, joined_at=111))
        self.assertFalse(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest=USER, observed_invite=LINK, joined_at=112))
        self.assertFalse(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest="b"*64, observed_invite=LINK2, joined_at=112))
        self.assertTrue(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest="b"*64, observed_invite=LINK, joined_at=112))
        snap = self.store.campaign_snapshot(actor_id=11, owner_id=11, campaign_id=campaign)
        self.assertEqual((snap["confirmed_joins"], snap["state"]), (2, "completed"))
        self.assertFalse(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest="c"*64, observed_invite=LINK, joined_at=113))
        self.assertEqual(self.store._db.execute(
            "SELECT count(*) FROM ad_campaign_joins WHERE campaign_id=?", (campaign,)
        ).fetchone()[0], 2)

    def test_duration_expiration_and_paused_campaign(self):
        campaign = self.make(mode="duration", target_joins=None)
        self.start(campaign)
        self.assertTrue(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest=USER, observed_invite=LINK, joined_at=111))
        self.store.change_campaign_state(actor_id=11, owner_id=11,
                                         campaign_id=campaign, action="pause", now=120)
        self.assertFalse(self.store.record_confirmed_join(
            campaign_id=campaign, user_digest="b"*64, observed_invite=LINK, joined_at=121))
        self.assertEqual(self.store.expire_campaigns(now=200), 1)
        self.assertEqual(self.store.expire_campaigns(now=201), 0)
        self.assertEqual(self.store.campaign_snapshot(actor_id=11, owner_id=11,
                         campaign_id=campaign)["state"], "completed")

    def test_owner_only_and_immutable_invite_link(self):
        campaign = self.make()
        with self.assertRaises(PermissionError):
            self.store.bind_campaign_invite(actor_id=12, owner_id=11,
                                             campaign_id=campaign, invite_link=LINK)
        self.start(campaign)
        with self.assertRaises(ValueError):
            self.store.bind_campaign_invite(actor_id=11, owner_id=11,
                                             campaign_id=campaign, invite_link=LINK2)
        with self.assertRaises(PermissionError):
            self.store.campaign_snapshot(actor_id=12, owner_id=11, campaign_id=campaign)
        with self.assertRaises(ValueError):
            self.store.change_campaign_state(actor_id=11, owner_id=11,
                                             campaign_id=campaign, action="start", now=111)
        self.assertEqual(self.store._db.execute(
            "SELECT count(*) FROM owner_audit WHERE action LIKE 'campaign_%'"
        ).fetchone()[0], 3)

    def test_different_campaigns_and_invite_links_are_isolated(self):
        one = self.make()
        two = self.make(chat_id=-100987654321)
        self.start(one)
        self.store.bind_campaign_invite(actor_id=11, owner_id=11,
                                        campaign_id=two, invite_link=LINK2, now=101)
        self.store.change_campaign_state(actor_id=11, owner_id=11,
                                         campaign_id=two, action="start", now=110)
        for cid, link in ((one, LINK), (two, LINK2)):
            self.assertTrue(self.store.record_confirmed_join(
                campaign_id=cid, user_digest=USER, observed_invite=link, joined_at=111))
        self.assertEqual(self.store.campaign_snapshot(actor_id=11, owner_id=11,
                         campaign_id=one)["confirmed_joins"], 1)
        self.assertEqual(self.store.campaign_snapshot(actor_id=11, owner_id=11,
                         campaign_id=two)["confirmed_joins"], 1)

    def test_bad_inputs_are_rejected_without_writes(self):
        bad = [
            {"actor_id": 12}, {"chat_id": 123}, {"chat_id": True},
            {"mode": "clicks"}, {"target_joins": 0},
            {"target_joins": True}, {"ends_at": 99},
            {"starts_at": float("nan")}, {"now": 0},
            {"mode": "duration", "target_joins": 1},
        ]
        for case in bad:
            with self.subTest(case=case), self.assertRaises((ValueError, PermissionError)):
                self.make(**case)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM ad_campaigns").fetchone()[0], 0)
        campaign = self.make()
        with self.assertRaises(ValueError):
            self.store.bind_campaign_invite(actor_id=11, owner_id=11,
                                             campaign_id=campaign,
                                             invite_link="https://example.com/fake", now=100)
        self.start(campaign)
        with self.assertRaises(ValueError):
            self.store.record_confirmed_join(campaign_id=campaign,
                                             user_digest="raw-user-123",
                                             observed_invite=LINK, joined_at=111)

    def test_persistence_after_reopen(self):
        campaign = self.make()
        self.start(campaign)
        self.store.record_confirmed_join(campaign_id=campaign,
                                         user_digest=USER, observed_invite=LINK, joined_at=111)
        self.store.close()
        self.addCleanup(lambda: None)
        with DurableJobStore(self.path) as reopened:
            snap = reopened.campaign_snapshot(actor_id=11, owner_id=11, campaign_id=campaign)
            self.assertEqual(snap["confirmed_joins"], 1)
            self.assertFalse(reopened.record_confirmed_join(
                campaign_id=campaign, user_digest=USER, observed_invite=LINK, joined_at=112))

    def test_rollback_if_owner_audit_fails(self):
        self.store._db.execute("""
            CREATE TRIGGER reject_campaign_audit BEFORE INSERT ON owner_audit
            WHEN NEW.action='campaign_create'
            BEGIN SELECT RAISE(ABORT,'no audit'); END
        """)
        with self.assertRaises(Exception):
            self.make()
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM ad_campaigns").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
