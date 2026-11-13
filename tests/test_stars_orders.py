"""Private Stars order registry must never grant value on an unverified quote."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from api.durable_jobs import DurableJobStore
from api.stars_orders import PRODUCTS

OWNER = 123456
NOW = 1794610000


class StarsOrdersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "orders.sqlite3"
        self.store = DurableJobStore(self.path)
        self.addCleanup(self.store.close)

    def test_catalog_prices_and_quote_are_server_owned_without_entitlement(self):
        self.assertEqual(
            {k: v["amount"] for k, v in PRODUCTS.items()},
            {"pro_30d": 149, "pack_10": 19, "pack_30": 49},
        )
        for sku in ("pro_30d", "pack_10", "pack_30"):
            with self.subTest(sku=sku):
                order = self.store.create_stars_order(OWNER, sku, now=NOW)
                self.assertEqual(order["sku"], sku)
                self.assertEqual(order["amount"], PRODUCTS[sku]["amount"])
                self.assertEqual(order["currency"], "XTR")
                self.assertEqual(order["status"], "pending")
                self.assertEqual(order["expires_at"], NOW + 1800)
                self.assertEqual(self.store.stars_order(OWNER, order["order_id"]), order)
                self.assertIsNone(self.store.stars_order(OWNER + 1, order["order_id"]))
                self.assertTrue(
                    self.store.can_precheckout_stars_order(
                        OWNER, order["order_id"], order["amount"], "XTR", now=NOW + 1,
                    )
                )
                self.assertFalse(
                    self.store.can_precheckout_stars_order(
                        OWNER, order["order_id"], order["amount"], "XTR", now=NOW + 1801,
                    )
                )
                self.assertFalse(
                    self.store.can_precheckout_stars_order(
                        OWNER + 1, order["order_id"], order["amount"], "XTR", now=NOW + 1,
                    )
                )
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["plan"], "free")
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 0)

    def test_only_exact_invoice_is_checkout_eligible(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.assertFalse(self.store.can_precheckout_stars_order(OWNER, order["order_id"], 20, "XTR", now=NOW))
        with self.assertRaises(ValueError):
            self.store.can_precheckout_stars_order(OWNER, order["order_id"], 19, "USD", now=NOW)
        with self.assertRaises(ValueError):
            self.store.can_precheckout_stars_order(OWNER, order["order_id"], True, "XTR", now=NOW)

    def test_confirmed_charge_deduplicates_without_granting_prepaid_value(self):
        order = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        record, created = self.store.record_stars_payment(
            OWNER, order["order_id"], "charge_001", 49, "XTR", now=NOW + 1,
        )
        self.assertTrue(created)
        self.assertEqual(record, {"order_id": order["order_id"], "sku": "pack_30", "status": "verified"})
        again, created = self.store.record_stars_payment(
            OWNER, order["order_id"], "charge_001", 49, "XTR", now=NOW + 2,
        )
        self.assertFalse(created)
        self.assertEqual(again, record)
        self.assertFalse(self.store.can_precheckout_stars_order(OWNER, order["order_id"], 49, "XTR", now=NOW + 2))
        self.assertEqual(self.store.stars_order(OWNER, order["order_id"])["status"], "verified")
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 2)["pack_remaining"], 0)
        self.assertIsNone(self.store.premium_expiry(OWNER))

    def test_bad_charge_owner_amount_currency_or_reuse_cannot_grant(self):
        first = self.store.create_stars_order(OWNER, "pro_30d", now=NOW)
        second = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(OWNER + 1, first["order_id"], "chargeA", 149, "XTR", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(OWNER, first["order_id"], "chargeA", 19, "XTR", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(OWNER, first["order_id"], "chargeA", 149, "USD", now=NOW)
        self.store.record_stars_payment(OWNER, first["order_id"], "chargeA", 149, "XTR", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(OWNER, first["order_id"], "chargeB", 149, "XTR", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(OWNER, second["order_id"], "chargeA", 19, "XTR", now=NOW)
        self.assertEqual(self.store.stars_order(OWNER, second["order_id"])["status"], "pending")
        self.assertIsNone(self.store.premium_expiry(OWNER))

    def test_receipts_persist_after_restart(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "chargeC", 19, "XTR", now=NOW)
        self.store.close()
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.stars_order(OWNER, order["order_id"])["status"], "verified")
            self.assertFalse(reopened.record_stars_payment(
                OWNER, order["order_id"], "chargeC", 19, "XTR", now=NOW + 1,
            )[1])
        # The original connection was closed before reopening; no live copy remains.

    def test_cross_connection_charge_replay_cannot_be_credited_twice(self):
        first = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        second = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        with DurableJobStore(self.path) as other:
            barrier = threading.Barrier(2)
            def confirm(item):
                store, order = item
                barrier.wait(timeout=5)
                try:
                    store.record_stars_payment(
                        OWNER, order["order_id"], "one_global_charge", 19, "XTR", now=NOW,
                    )
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcome = list(pool.map(confirm, [(self.store, first), (other, second)]))
            self.assertCountEqual(outcome, [True, False])
        rows = self.store._db.execute("SELECT status FROM stars_orders ORDER BY created_at,order_id").fetchall()
        self.assertCountEqual([x[0] for x in rows], ["pending", "verified"])

    def test_validation_rejects_untrusted_fields(self):
        for sku in ("", "unknown", "Pro", 123):
            with self.subTest(sku=sku), self.assertRaises(ValueError):
                self.store.create_stars_order(OWNER, sku, now=NOW)
        for user in (0, True, "123456"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                self.store.create_stars_order(user, "pack_10", now=NOW)
        for stamp in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(now=stamp), self.assertRaises(ValueError):
                self.store.create_stars_order(OWNER, "pack_10", now=stamp)
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        for charge in ("", "bad charge", "x" * 257, "\n"):
            with self.subTest(charge=charge), self.assertRaises(ValueError):
                self.store.record_stars_payment(OWNER, order["order_id"], charge, 19, "XTR", now=NOW)
        self.assertEqual(self.store.stars_order(OWNER, order["order_id"])["status"], "pending")


if __name__ == "__main__":
    unittest.main()
