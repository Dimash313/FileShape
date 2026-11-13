"""Durable Free/Pro quotas and prepaid-pack regressions: no checkout claims."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from api.durable_jobs import DurableJobStore
from api.usage_ledger import OperationQuotaExceeded


class UsageQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "usage.sqlite3"
        self.day_start = datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp()

    def key(self, index):
        return f"fileshape:operation:{index:06d}"

    def test_free_limit_and_utc_boundary(self):
        with DurableJobStore(self.path) as store:
            state = store.usage_snapshot(11, now=self.day_start)
            self.assertEqual((state["plan"], state["daily_limit"], state["daily_used"], state["pack_remaining"]), ("free", 10, 0, 0))
            for n in range(10):
                reservation = store.reserve_operation(11, self.key(n), now=self.day_start + 1)
                self.assertEqual(reservation["source"], "daily")
                self.assertTrue(reservation["created"])
            self.assertEqual(store.usage_snapshot(11, now=self.day_start + 3600)["daily_remaining"], 0)
            with self.assertRaises(OperationQuotaExceeded):
                store.reserve_operation(11, self.key(10), now=self.day_start + 86399)
            next_day = store.usage_snapshot(11, now=self.day_start + 86400)
            self.assertEqual((next_day["daily_used"], next_day["daily_remaining"]), (0, 10))
            self.assertEqual(store.reserve_operation(11, self.key(10), now=self.day_start + 86400)["source"], "daily")
            self.assertEqual(store.usage_snapshot(11, now=self.day_start + 86400)["daily_used"], 1)

    def test_pro_limit_and_expiry(self):
        with DurableJobStore(self.path) as store:
            expiry, _ = store.grant_premium(11, 86400, "admin:premium:11", now=self.day_start)
            state = store.usage_snapshot(11, now=self.day_start + 1)
            self.assertEqual((state["plan"], state["daily_limit"], state["pro_expires_at"]), ("pro", 100, expiry))
            for n in range(100):
                store.reserve_operation(11, self.key(n), now=self.day_start + 1)
            with self.assertRaises(OperationQuotaExceeded):
                store.reserve_operation(11, self.key(100), now=self.day_start + 1)
            later = store.usage_snapshot(11, now=self.day_start + 86400)
            self.assertEqual((later["plan"], later["daily_limit"], later["daily_remaining"], later["pro_expires_at"]), ("free", 10, 10, None))

    def test_upgrade_during_day_increases_remaining_limit(self):
        with DurableJobStore(self.path) as store:
            for n in range(10):
                store.reserve_operation(11, self.key(n), now=self.day_start + 1)
            store.grant_premium(11, 86400, "upgrade:premium:11", now=self.day_start + 2)
            state = store.usage_snapshot(11, now=self.day_start + 3)
            self.assertEqual((state["daily_used"], state["daily_remaining"]), (10, 90))

    def test_pack_only_after_daily_and_refund_on_failure(self):
        with DurableJobStore(self.path) as store:
            self.assertEqual(store.grant_operation_pack(11, 10, "stars:paid:transaction:1", now=self.day_start), (10, True))
            for n in range(10):
                store.reserve_operation(11, self.key(n), now=self.day_start + 1)
            result = store.reserve_operation(11, self.key(10), now=self.day_start + 2)
            self.assertEqual(result["source"], "pack")
            self.assertEqual(store.usage_snapshot(11, now=self.day_start + 3)["pack_remaining"], 9)
            self.assertTrue(store.settle_operation(11, self.key(10), success=False, now=self.day_start + 3))
            self.assertFalse(store.settle_operation(11, self.key(10), success=False, now=self.day_start + 4))
            self.assertEqual(store.usage_snapshot(11, now=self.day_start + 4)["pack_remaining"], 10)
            with self.assertRaises(ValueError):
                store.settle_operation(11, self.key(10), success=True, now=self.day_start + 5)
            self.assertFalse(store.reserve_operation(11, self.key(10), now=self.day_start + 5)["created"])
            self.assertEqual(store.reserve_operation(11, self.key(11), now=self.day_start + 6)["source"], "pack")
            self.assertTrue(store.settle_operation(11, self.key(11), success=True, now=self.day_start + 7))
            self.assertFalse(store.settle_operation(11, self.key(11), success=True, now=self.day_start + 8))
            self.assertEqual(store.usage_snapshot(11, now=self.day_start + 8)["pack_remaining"], 9)

    def test_release_daily_frees_daily_not_pack(self):
        with DurableJobStore(self.path) as store:
            store.reserve_operation(11, self.key(0), now=self.day_start)
            store.settle_operation(11, self.key(0), success=False, now=self.day_start + 1)
            state = store.usage_snapshot(11, now=self.day_start + 1)
            self.assertEqual((state["daily_used"], state["daily_remaining"]), (0, 10))

    def test_replayed_pack_grant_owner_and_size_conflicts(self):
        with DurableJobStore(self.path) as store:
            self.assertEqual(store.grant_operation_pack(11, 30, "stars:transaction:unique:1", now=self.day_start), (30, True))
            self.assertEqual(store.grant_operation_pack(11, 30, "stars:transaction:unique:1", now=self.day_start + 1), (30, False))
            with self.assertRaises(ValueError):
                store.grant_operation_pack(12, 30, "stars:transaction:unique:1", now=self.day_start + 2)
            with self.assertRaises(ValueError):
                store.grant_operation_pack(11, 10, "stars:transaction:unique:1", now=self.day_start + 2)
            self.assertEqual(store.usage_snapshot(12, now=self.day_start)["pack_remaining"], 0)
            self.assertEqual(store.usage_snapshot(11, now=self.day_start)["pack_remaining"], 30)

    def test_cross_connection_race_never_overspends(self):
        with DurableJobStore(self.path) as first, DurableJobStore(self.path) as second:
            def reserve(i):
                try:
                    (first if i % 2 == 0 else second).reserve_operation(11, self.key(i), now=self.day_start)
                    return True
                except OperationQuotaExceeded:
                    return False
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(reserve, range(32)))
            self.assertEqual(sum(results), 10)
            self.assertEqual(first.usage_snapshot(11, now=self.day_start)["daily_used"], 10)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.usage_snapshot(11, now=self.day_start)["daily_used"], 10)

    def test_pack_replay_and_cross_owner_operation_isolation(self):
        with DurableJobStore(self.path) as a:
            a.grant_operation_pack(11, 10, "stars:transaction:unique:2", now=self.day_start)
            self.assertTrue(a.reserve_operation(11, self.key(0), now=self.day_start)["created"])
            self.assertFalse(a.reserve_operation(11, self.key(0), now=self.day_start)["created"])
            with self.assertRaises(PermissionError):
                a.reserve_operation(12, self.key(0), now=self.day_start)
            with self.assertRaises(PermissionError):
                a.settle_operation(12, self.key(0), success=False, now=self.day_start)
            self.assertEqual(a.usage_snapshot(11, now=self.day_start)["daily_used"], 1)
        with DurableJobStore(self.path) as b:
            self.assertTrue(b.settle_operation(11, self.key(0), success=True, now=self.day_start + 1))
            self.assertEqual(b.usage_snapshot(11, now=self.day_start)["daily_used"], 1)

    def test_invalid_inputs_never_write(self):
        with DurableJobStore(self.path) as store:
            for owner in (False, 0, -1, "11"):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    store.reserve_operation(owner, self.key(0), now=self.day_start)
            for key in ("short", "", "untrusted/key", "x" * 161):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    store.reserve_operation(11, key, now=self.day_start)
            for timestamp in (True, 0, -1, float("nan"), float("inf")):
                with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                    store.reserve_operation(11, self.key(0), now=timestamp)
            for count in (0, 1, 20, 100, True):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    store.grant_operation_pack(11, count, "stars:transaction:bad", now=self.day_start)
            with self.assertRaises(LookupError):
                store.settle_operation(11, self.key(99), success=False, now=self.day_start)
            self.assertEqual(store.usage_snapshot(11, now=self.day_start)["daily_used"], 0)


if __name__ == "__main__":
    unittest.main()
