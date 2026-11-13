"""Campaign bridge regression tests: signed payloads and exact attribution."""
import tempfile
import unittest
from pathlib import Path

from api.campaign_bridge import JoinReplayGuard, sign_join_assertion
from api.durable_jobs import DurableJobStore

TOKEN = "123456:TEST"
LINK = "https://t.me/+Abcdefgh12345678"
CHAT = -100123456789
NOW = 1794570000


def payload(**overrides):
    return dict(chat_id=CHAT, invite_link=LINK,
                user_digest="a"*64, joined_at=NOW) | overrides


class CampaignBridgeTests(unittest.TestCase):
    def test_signed_assertion_replay_tamper_expiry(self):
        p = payload()
        sig = sign_join_assertion(TOKEN, p, NOW, "a"*32)
        guard = JoinReplayGuard()
        guard.verify(TOKEN, p, str(NOW), "a"*32, sig, now=NOW)
        with self.assertRaises(ValueError):
            guard.verify(TOKEN, p, str(NOW), "a"*32, sig, now=NOW)
        for altered in (payload(chat_id=CHAT-1),
                        payload(invite_link="https://t.me/+OtherLink1234567"),
                        payload(user_digest="b"*64), payload(joined_at=NOW-301)):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                JoinReplayGuard().verify(TOKEN, altered, str(NOW), "a"*32, sig, now=NOW)
        with self.assertRaises(ValueError):
            JoinReplayGuard().verify(TOKEN, p, str(NOW), "a"*32, sig, now=NOW+301)

    def test_malformed_and_extra_fields_rejected(self):
        for bad in (payload(chat_id=True), payload(joined_at=True),
                    payload(user_digest="123"), payload(invite_link="https://fake"),
                    payload(campaign_id="untrusted")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sign_join_assertion(TOKEN, bad, NOW, "a"*32)

    def test_exact_channel_link_and_join_target(self):
        with tempfile.TemporaryDirectory() as directory:
            with DurableJobStore(Path(directory)/"jobs.sqlite3") as store:
                cid = store.create_campaign(
                    actor_id=11, owner_id=11, chat_id=CHAT, mode="joins",
                    starts_at=NOW-100, ends_at=NOW+100, target_joins=1, now=NOW-100)
                store.bind_campaign_invite(
                    actor_id=11, owner_id=11, campaign_id=cid,
                    invite_link=LINK, now=NOW-99)
                store.change_campaign_state(
                    actor_id=11, owner_id=11, campaign_id=cid,
                    action="start", now=NOW-90)
                self.assertFalse(store.record_attributed_join(**payload(chat_id=CHAT-1)))
                self.assertFalse(store.record_attributed_join(**payload(
                    invite_link="https://t.me/+OtherLink1234567")))
                self.assertTrue(store.record_attributed_join(**payload()))
                self.assertFalse(store.record_attributed_join(**payload()))
                snap = store.campaign_snapshot(
                    actor_id=11, owner_id=11, campaign_id=cid)
                self.assertEqual((snap["confirmed_joins"], snap["state"]),
                                 (1, "completed"))


if __name__ == "__main__":
    unittest.main()
