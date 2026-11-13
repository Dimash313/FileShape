"""Access-policy unit regressions; integration with bot/API is a later PR."""
import unittest
from datetime import datetime, timedelta, timezone

from api.access_policy import (
    AccessDecision, RequiredChannel, decide_access, membership_confirmed,
)


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


class AccessPolicyTests(unittest.TestCase):
    def channel(self, chat_id=-1001, **kwargs):
        return RequiredChannel(chat_id, NOW - timedelta(days=1), **kwargs)

    def decision(self, observations, channels=None, premium_until=None):
        return decide_access(
            premium_until=premium_until,
            channels=tuple(channels if channels is not None else [self.channel()]),
            observations=observations,
            now=NOW,
        )

    def test_confirmed_telegram_statuses(self):
        for status in ("creator", "administrator", "member"):
            self.assertTrue(membership_confirmed(status))
        self.assertTrue(membership_confirmed("restricted", is_member=True))
        for status in ("left", "kicked", "restricted", None, "unknown"):
            self.assertFalse(membership_confirmed(status))
        self.assertFalse(membership_confirmed("restricted", is_member=False))

    def test_free_requires_all_channels(self):
        channels = [self.channel(), self.channel(-1002)]
        self.assertEqual(self.decision({-1001: ("member", None), -1002: ("left", None)}, channels),
                         AccessDecision.SUBSCRIPTION_REQUIRED)
        self.assertEqual(self.decision({-1001: ("member", None), -1002: ("administrator", None)}, channels),
                         AccessDecision.ALLOWED)

    def test_unavailable_is_not_membership(self):
        self.assertEqual(self.decision({}), AccessDecision.VERIFICATION_UNAVAILABLE)
        self.assertEqual(self.decision({-1001: None}), AccessDecision.VERIFICATION_UNAVAILABLE)
        self.assertEqual(self.decision({-1001: ("left", None)}), AccessDecision.SUBSCRIPTION_REQUIRED)

    def test_premium_bypass_expires_at_exact_boundary(self):
        self.assertEqual(self.decision({}, premium_until=NOW + timedelta(seconds=1)), AccessDecision.ALLOWED)
        self.assertEqual(self.decision({}, premium_until=NOW), AccessDecision.VERIFICATION_UNAVAILABLE)

    def test_scheduled_and_disabled_channels(self):
        future = RequiredChannel(-1002, NOW + timedelta(seconds=1))
        expired = self.channel(-1003, ends_at=NOW)
        disabled = self.channel(-1004, enabled=False)
        self.assertEqual(self.decision({}, [future, expired, disabled]), AccessDecision.ALLOWED)
        self.assertEqual(self.decision({}, [self.channel(-1001, ends_at=NOW + timedelta(seconds=1))]),
                         AccessDecision.VERIFICATION_UNAVAILABLE)

    def test_duplicate_channels_rejected(self):
        with self.assertRaises(ValueError):
            self.decision({}, [self.channel(), self.channel()])

    def test_invalid_dates_and_ids_rejected(self):
        with self.assertRaises(ValueError):
            RequiredChannel(True, NOW)
        with self.assertRaises(ValueError):
            RequiredChannel(-1001, NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.decision({}, premium_until=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            decide_access(premium_until=None, channels=(), observations={},
                          now=NOW.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
