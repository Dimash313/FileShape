"""FileShape 4.21 quota ledger: concurrency, UTC reset, idempotency, refunds."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from api.durable_jobs import DurableJobStore
from api.operation_quotas import QuotaClaimRefunded, QuotaExhausted


class OperationQuotaLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.sqlite3"

    def test_free_limit_and_utc_boundary(self):
        with DurableJobStore(self.path) as store:
            for n in range(10):
                self.assertEqual(store.claim_operation(15, f"conversion:{n:020d}", now=100), ("daily", True))
            self.assertEqual(store.quota_status(15, now=100)["daily_remaining"], 0)
            with self.assertRaises(QuotaExhausted):
                store.claim_operation(15, "conversion:limit-reached:0001", now=100)
            self.assertEqual(store.quota_status(15, now=86399)["total_remaining"], 0)
            self.assertEqual(store.quota_status(15, now=86400)["daily_remaining"], 10)
            self.assertEqual(store.claim_operation(15, "conversion:newday:00001", now=86400),
                             ("daily", True))
            self.assertEqual(store.quota_status(15, now=86400)["reset_at"], 172800)

    def test_pro_limit_and_expiry_without_erasing_usage(self):
        with DurableJobStore(self.path) as store:
            store.grant_premium(15, 10000, "admin:premium:grant:001", now=1000)
            self.assertEqual(store.quota_status(15, now=1001)["tier"], "pro")
            self.assertEqual(store.quota_status(15, now=1001)["daily_limit"], 100)
            for n in range(15):
                store.claim_operation(15, f"conversion:pro:{n:020d}", now=1001)
            after_expiry = store.quota_status(15, now=11000)
            self.assertEqual(after_expiry["tier"], "free")
            self.assertEqual(after_expiry["daily_used"], 15)
            self.assertEqual(after_expiry["daily_remaining"], 0)
            with self.assertRaises(QuotaExhausted):
                store.claim_operation(15, "conversion:expired:0001", now=11000)

    def test_credits_only_after_daily_limit(self):
        with DurableJobStore(self.path) as store:
            self.assertEqual(store.grant_operation_pack(15, 10, "payment:pack:first:15", now=100),
                             (10, True))
            for n in range(10):
                self.assertEqual(store.claim_operation(15, f"conversion:free:{n:020d}", now=100)[0], "daily")
            self.assertEqual(store.claim_operation(15, "conversion:extra-credit:1", now=100),
                             ("pack", True))
            status = store.quota_status(15, now=100)
            self.assertEqual((status["daily_used"], status["extra_remaining"], status["total_remaining"]),
                             (10, 9, 9))
            self.assertEqual(store.grant_operation_pack(15, 30, "payment:pack:second:15", now=100),
                             (39, True))
            self.assertEqual(store.grant_operation_pack(15, 10, "payment:pack:first:15", now=500),
                             (39, False))

    def test_duplicate_claim_no_double_charge_and_refund_once(self):
        with DurableJobStore(self.path) as store:
            self.assertEqual(store.claim_operation(20, "conversion:idempotent:001", now=100),
                             ("daily", True))
            self.assertEqual(store.claim_operation(20, "conversion:idempotent:001", now=86400),
                             ("daily", False))
            with self.assertRaises(ValueError):
                store.claim_operation(21, "conversion:idempotent:001", now=100)
            self.assertTrue(store.refund_operation(20, "conversion:idempotent:001", now=86400))
            self.assertFalse(store.refund_operation(20, "conversion:idempotent:001", now=86401))
            self.assertEqual(store.quota_status(20, now=100)["daily_used"], 0)
            self.assertEqual(store.quota_status(20, now=86400)["daily_used"], 0)
            with self.assertRaises(QuotaClaimRefunded):
                store.claim_operation(20, "conversion:idempotent:001", now=86401)

    def test_pack_refund_after_midnight_and_owner_isolation(self):
        with DurableJobStore(self.path) as store:
            store.grant_operation_pack(15, 30, "payment:pack:refund:15", now=100)
            for n in range(10):
                store.claim_operation(15, f"conversion:basic:{n:020d}", now=100)
            store.claim_operation(15, "conversion:pack-refund:01", now=100)
            self.assertEqual(store.quota_status(15, now=100)["extra_remaining"], 29)
            with self.assertRaises(ValueError):
                store.refund_operation(16, "conversion:pack-refund:01", now=86400)
            self.assertTrue(store.refund_operation(15, "conversion:pack-refund:01", now=86400))
            self.assertEqual(store.quota_status(15, now=86400)["extra_remaining"], 30)
            self.assertFalse(store.refund_operation(15, "conversion:pack-refund:01", now=86400))
            self.assertFalse(store.refund_operation(15, "conversion:unknown:000001", now=86400))

    def test_grant_replay_conflicts_and_invalid_inputs(self):
        with DurableJobStore(self.path) as store:
            store.grant_operation_pack(15, 10, "payment:grant:unique:001", now=100)
            for owner, units in ((16, 10), (15, 30)):
                with self.assertRaises(ValueError):
                    store.grant_operation_pack(owner, units, "payment:grant:unique:001", now=100)
            self.assertEqual(store.quota_status(16, now=100)["extra_remaining"], 0)
            for owner in (0, True, "15", -1):
                with self.assertRaises(ValueError):
                    store.quota_status(owner, now=100)
            for units in (0, -1, True, 11, 100):
                with self.assertRaises(ValueError):
                    store.grant_operation_pack(15, units, "payment:grant:invalid:1", now=100)
            for key in ("short", "illegal/key", "a" * 161):
                with self.assertRaises(ValueError):
                    store.grant_operation_pack(15, 10, key, now=100)
            for claim in ("short", "../escape", "a" * 129):
                with self.assertRaises(ValueError):
                    store.claim_operation(15, claim, now=100)
            for invalid_now in (0, -1, True, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    store.quota_status(15, now=invalid_now)
            self.assertEqual(store.quota_status(15, now=100)["extra_remaining"], 10)

    def test_sqlite_reopen_and_cross_connection_atomic_limit(self):
        with DurableJobStore(self.path) as first, DurableJobStore(self.path) as second:
            def try_claim(n):
                store = first if n % 2 == 0 else second
                try:
                    return store.claim_operation(11, f"conversion:parallel:{n:020d}", now=100)
                except QuotaExhausted:
                    return None

            with ThreadPoolExecutor(max_workers=12) as executor:
                results = list(executor.map(try_claim, range(48)))
            self.assertEqual(sum(item is not None for item in results), 10)
            self.assertEqual(first.quota_status(11, now=100)["daily_used"], 10)
            self.assertEqual(second.quota_status(11, now=100)["daily_used"], 10)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.quota_status(11, now=100)["daily_used"], 10)
            self.assertEqual(reopened.quota_status(12, now=100)["daily_used"], 0)

    def test_pack_grants_and_refunds_survive_reopen(self):
        with DurableJobStore(self.path) as store:
            store.grant_operation_pack(17, 30, "payment:durable:pack:017", now=100)
            for n in range(10):
                store.claim_operation(17, f"conversion:durable:{n:020d}", now=100)
            store.claim_operation(17, "conversion:durable:extra", now=100)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.quota_status(17, now=100)["extra_remaining"], 29)
            self.assertTrue(reopened.refund_operation(17, "conversion:durable:extra", now=200))
            self.assertEqual(reopened.grant_operation_pack(17, 30, "payment:durable:pack:017", now=200),
                             (30, False))

    def test_old_usage_prunes_without_erasing_grant_deduplication(self):
        with DurableJobStore(self.path) as store:
            store.grant_operation_pack(11, 10, "payment:retained:pack:11", now=100)
            store.claim_operation(11, "conversion:outdated:001", now=100)
            self.assertEqual(store.prune_operation_quotas(now=100 + 91 * 86400), (1, 1))
            self.assertEqual(store.grant_operation_pack(11, 10, "payment:retained:pack:11",
                                                         now=100 + 91 * 86400), (10, False))
            self.assertEqual(store.quota_status(11, now=100 + 91 * 86400)["extra_remaining"], 10)


if __name__ == "__main__":
    unittest.main()
