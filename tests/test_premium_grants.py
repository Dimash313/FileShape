"""Premium grant storage regressions; no billing/checkout integration yet."""
import tempfile
import unittest
from pathlib import Path

from api.durable_jobs import DurableJobStore


class PremiumGrantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.sqlite3"

    def test_first_grant_and_idempotent_replay(self):
        with DurableJobStore(self.path) as store:
            self.assertIsNone(store.premium_expiry(11))
            self.assertEqual(store.grant_premium(11, 86400, "referral:milestone:11:1", now=1000),
                             (87400, True))
            self.assertEqual(store.grant_premium(11, 86400, "referral:milestone:11:1", now=2000),
                             (87400, False))
            self.assertEqual(store.premium_expiry(11), 87400)

    def test_extension_from_current_expiry_and_from_now(self):
        with DurableJobStore(self.path) as store:
            store.grant_premium(11, 100, "admin:grant:initial", now=1000)
            self.assertEqual(store.grant_premium(11, 50, "admin:grant:extension", now=1050),
                             (1150, True))
            self.assertEqual(store.grant_premium(11, 20, "admin:grant:later", now=2000),
                             (2020, True))

    def test_cross_connection_serialization_and_reopen(self):
        with DurableJobStore(self.path) as a, DurableJobStore(self.path) as b:
            a.grant_premium(11, 100, "payment:unique:001", now=1000)
            b.grant_premium(11, 100, "payment:unique:002", now=1000)
            self.assertEqual(a.premium_expiry(11), 1200)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.premium_expiry(11), 1200)
            self.assertEqual(reopened.grant_premium(11, 100, "payment:unique:001", now=2000),
                             (1100, False))
            self.assertEqual(reopened.premium_expiry(11), 1200)

    def test_cross_owner_replay_cannot_grant(self):
        with DurableJobStore(self.path) as store:
            store.grant_premium(11, 100, "payment:unique:001", now=1000)
            with self.assertRaises(ValueError):
                store.grant_premium(12, 100, "payment:unique:001", now=1000)
            self.assertIsNone(store.premium_expiry(12))

    def test_conflicting_duration_cannot_grant(self):
        with DurableJobStore(self.path) as store:
            store.grant_premium(11, 100, "payment:unique:001", now=1000)
            with self.assertRaises(ValueError):
                store.grant_premium(11, 200, "payment:unique:001", now=1000)
            self.assertEqual(store.premium_expiry(11), 1100)

    def test_invalid_inputs_do_not_write(self):
        with DurableJobStore(self.path) as store:
            for owner in (True, 0, -1, "11"):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    store.grant_premium(owner, 10, "admin:grant:valid", now=1000)
            for duration in (True, 0, -1, 367 * 86400, 1.5):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    store.grant_premium(11, duration, "admin:grant:valid", now=1000)
            for key in ("short", "unsafe/key", "", "a" * 161):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    store.grant_premium(11, 10, key, now=1000)
            for timestamp in (0, -1, float("nan"), float("inf")):
                with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                    store.grant_premium(11, 10, "admin:grant:valid", now=timestamp)
            self.assertIsNone(store.premium_expiry(11))


if __name__ == "__main__":
    unittest.main()
