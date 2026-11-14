"""Private Stars order registry must never grant value on an unverified quote."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
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


    def test_unpaid_quote_cap_and_private_expired_quote_pruning(self):
        orders = [
            self.store.create_stars_order(OWNER, "pack_10", now=NOW)
            for _ in range(5)
        ]
        with self.assertRaisesRegex(ValueError, "Too many active"):
            self.store.create_stars_order(OWNER, "pack_10", now=NOW + 1)
        # A verified payment is a financial record, not an expirable quote.
        self.store.record_stars_payment(
            OWNER, orders[0]["order_id"], "retained_charge", 19, "XTR", now=NOW + 1,
        )
        self.assertEqual(self.store.prune_expired_stars_quotes(
            now=NOW + 1800 + 14 * 86400 + 1,
        ), 4)
        self.assertEqual(self.store.prune_expired_stars_quotes(
            now=NOW + 1800 + 14 * 86400 + 1,
        ), 0)
        self.assertEqual(self.store.stars_order(
            OWNER, orders[0]["order_id"],
        )["status"], "verified")
        for order in orders[1:]:
            self.assertIsNone(self.store.stars_order(OWNER, order["order_id"]))
        self.assertEqual(self.store.create_stars_order(
            OWNER, "pack_10", now=NOW + 1800 + 14 * 86400 + 2,
        )["status"], "pending")

    def test_approved_invoice_retained_even_after_14_day_cleanup(self):
        protected = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        disposable = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.assertEqual(self.store._db.execute(
            "SELECT never_prechecked FROM stars_orders WHERE order_id=?",
            (protected["order_id"],),
        ).fetchone()[0], 1)
        self.assertTrue(self.store.can_precheckout_stars_order(
            OWNER, protected["order_id"], 19, "XTR", now=NOW + 1,
        ))
        self.assertEqual(self.store._db.execute(
            "SELECT never_prechecked FROM stars_orders WHERE order_id=?",
            (protected["order_id"],),
        ).fetchone()[0], 0)
        # The API may be offline for weeks after Telegram accepted checkout.
        late = NOW + 1800 + 14 * 86400 + 100
        self.assertEqual(self.store.prune_expired_stars_quotes(now=late), 1)
        self.assertIsNone(self.store.stars_order(OWNER, disposable["order_id"]))
        self.assertEqual(
            self.store.stars_order(OWNER, protected["order_id"])["status"], "pending",
        )
        result, created = self.store.record_stars_payment(
            OWNER, protected["order_id"], "paid_after_outage",
            19, "XTR", now=late,
        )
        self.assertTrue(created)
        self.assertEqual(result["status"], "verified")
        _, credited = self.store.fulfill_stars_order(
            OWNER, protected["order_id"], now=late,
        )
        self.assertTrue(credited)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=late)["pack_remaining"], 10)

    def test_rejected_precheckout_never_changes_disposable_quote_flag(self):
        q = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER, q["order_id"], 30, "XTR", now=NOW + 1,
        ))
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER + 1, q["order_id"], 49, "XTR", now=NOW + 1,
        ))
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER, q["order_id"], 49, "XTR", now=NOW + 1801,
        ))
        self.assertEqual(self.store._db.execute(
            "SELECT never_prechecked FROM stars_orders WHERE order_id=?",
            (q["order_id"],),
        ).fetchone()[0], 1)
        self.assertEqual(
            self.store.prune_expired_stars_quotes(now=NOW + 1800 + 14*86400 + 1),
            1,
        )

    def test_existing_stars_database_migrates_without_dropping_pending_orders(self):
        legacy_path = Path(self.temp.name) / "legacy_orders.sqlite3"
        with sqlite3.connect(legacy_path) as db:
            db.execute("""CREATE TABLE stars_orders (
                order_id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                sku TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                telegram_charge_id TEXT UNIQUE,
                verified_at REAL,
                fulfilled_at REAL,
                refunded_at REAL
            )""")
            db.execute(
                """INSERT INTO stars_orders
                   (order_id,owner_id,sku,amount,currency,status,created_at,expires_at)
                   VALUES(?,?,?,?,?,'pending',?,?)""",
                ("a"*32, OWNER, "pack_10", 19, "XTR", NOW, NOW+1800),
            )
        with DurableJobStore(legacy_path) as migrated:
            self.assertEqual(migrated._db.execute(
                "SELECT never_prechecked FROM stars_orders WHERE order_id=?", ("a"*32,),
            ).fetchone()[0], 0)
            self.assertEqual(
                migrated.prune_expired_stars_quotes(
                    now=NOW + 1800 + 14 * 86400 + 100,
                ),
                0,
            )
            self.assertEqual(migrated.stars_order(OWNER, "a"*32)["status"], "pending")
            self.assertTrue(migrated.can_precheckout_stars_order(
                OWNER, "a"*32, 19, "XTR", now=NOW + 10,
            ))
            self.assertEqual(migrated._db.execute(
                "SELECT never_prechecked FROM stars_orders WHERE order_id=?", ("a"*32,),
            ).fetchone()[0], 0)

    def test_pack_precheckout_rejects_capacity_overflow_before_charging(self):
        self.store._db.execute(
            "INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)",
            (OWNER, 9995),
        )
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER, order["order_id"], 19, "XTR", now=NOW + 1,
        ))
        self.assertEqual(
            self.store._db.execute(
                "SELECT never_prechecked FROM stars_orders WHERE order_id=?",
                (order["order_id"],),
            ).fetchone()[0], 1,
        )
        self.assertEqual(self.store.stars_order(OWNER, order["order_id"])["status"], "pending")
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 9995)
        self.store._db.execute(
            "UPDATE operation_pack_balances SET balance=9980 WHERE owner_id=?", (OWNER,),
        )
        self.assertTrue(self.store.can_precheckout_stars_order(
            OWNER, order["order_id"], 19, "XTR", now=NOW + 2,
        ))
        self.assertEqual(
            self.store._db.execute(
                "SELECT never_prechecked FROM stars_orders WHERE order_id=?",
                (order["order_id"],),
            ).fetchone()[0], 0,
        )

    def test_two_approved_pack_invoices_cannot_overreserve_same_headroom(self):
        self.store._db.execute(
            "INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)",
            (OWNER, 9975),
        )
        first = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        second = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        self.assertTrue(self.store.can_precheckout_stars_order(
            OWNER, first["order_id"], 19, "XTR", now=NOW + 1,
        ))
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER, second["order_id"], 49, "XTR", now=NOW + 1,
        ))
        self.store.record_stars_payment(
            OWNER, first["order_id"], "cap_first", 19, "XTR", now=NOW + 2,
        )
        self.store.fulfill_stars_order(OWNER, first["order_id"], now=NOW + 2)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 2)["pack_remaining"], 9985)
        self.assertFalse(self.store.can_precheckout_stars_order(
            OWNER, second["order_id"], 49, "XTR", now=NOW + 3,
        ))

    def test_trusted_pack_grant_respects_unfulfilled_approved_invoice_capacity(self):
        self.store._db.execute(
            "INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)",
            (OWNER, 9960),
        )
        order = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        self.assertTrue(self.store.can_precheckout_stars_order(
            OWNER, order["order_id"], 49, "XTR", now=NOW + 1,
        ))
        with self.assertRaisesRegex(ValueError, "approved Stars invoices"):
            self.store.grant_operation_pack(
                OWNER, 30, "trusted:high:000001", now=NOW + 2,
            )
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 2)["pack_remaining"], 9960)
        self.assertEqual(self.store.grant_operation_pack(
            OWNER, 10, "trusted:lower:00001", now=NOW + 3,
        ), (9970, True))
        self.store.record_stars_payment(
            OWNER, order["order_id"], "cap_reserved", 49, "XTR", now=NOW + 4,
        )
        result, created = self.store.fulfill_stars_order(
            OWNER, order["order_id"], now=NOW + 4,
        )
        self.assertEqual(result["status"], "fulfilled")
        self.assertTrue(created)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 4)["pack_remaining"], 10000)

    def test_paid_and_refunded_history_transitions_without_any_paid_entitlement(self):
        order = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        result, created = self.store.record_paid_and_refunded_stars_order(
            OWNER, order["order_id"], "telegram_history_refund", 49, "XTR", now=NOW + 1,
        )
        self.assertEqual(result["status"], "refunded")
        self.assertTrue(created)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 2)["pack_remaining"], 0)
        self.assertIsNone(self.store.premium_expiry(OWNER))
        replay, created = self.store.record_paid_and_refunded_stars_order(
            OWNER, order["order_id"], "telegram_history_refund", 49, "XTR", now=NOW + 2,
        )
        self.assertFalse(created)
        self.assertEqual(replay["status"], "refunded")
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(
                OWNER, order["order_id"], "telegram_history_refund", 49, "XTR", now=NOW + 3,
            )
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW + 3)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.stars_order(OWNER, order["order_id"])["status"], "refunded")
            self.assertEqual(reopened.usage_snapshot(OWNER, now=NOW + 3)["pack_remaining"], 0)

    def test_refunded_history_rejects_wrong_price_owner_and_charge_reuse(self):
        first = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        second = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        with self.assertRaises(ValueError):
            self.store.record_paid_and_refunded_stars_order(
                OWNER, first["order_id"], "refund_history", 20, "XTR", now=NOW,
            )
        with self.assertRaises(ValueError):
            self.store.record_paid_and_refunded_stars_order(
                OWNER + 1, first["order_id"], "refund_history", 19, "XTR", now=NOW,
            )
        self.assertEqual(self.store.stars_order(OWNER, first["order_id"])["status"], "pending")
        self.store.record_paid_and_refunded_stars_order(
            OWNER, first["order_id"], "refund_history", 19, "XTR", now=NOW,
        )
        with self.assertRaises(ValueError):
            self.store.record_paid_and_refunded_stars_order(
                OWNER, second["order_id"], "refund_history", 19, "XTR", now=NOW,
            )
        self.assertEqual(self.store.stars_order(OWNER, second["order_id"])["status"], "pending")

    def test_verified_order_fulfills_once_and_survives_restart(self):
        order = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "txn_300", 49, "XTR", now=NOW)
        result, new = self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        self.assertTrue(new)
        self.assertEqual(result["status"], "fulfilled")
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 30)
        self.assertFalse(self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW + 2)[1])
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER + 1, order["order_id"], now=NOW)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 30)
        with DurableJobStore(self.path) as reopened:
            self.assertEqual(reopened.stars_order(OWNER, order["order_id"])["status"], "fulfilled")
            self.assertFalse(reopened.fulfill_stars_order(OWNER, order["order_id"], now=NOW + 3)[1])
            self.assertEqual(reopened.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 30)

    def test_pro_payments_extend_entitlement_and_refund_retracts_remaining_time(self):
        for i in range(2):
            order = self.store.create_stars_order(OWNER, "pro_30d", now=NOW)
            self.store.record_stars_payment(
                OWNER, order["order_id"], f"charge_premium_{i}", 149, "XTR", now=NOW,
            )
            self.assertTrue(self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)[1])
            if i == 0:
                first = order
        self.assertEqual(self.store.premium_expiry(OWNER), NOW + 60 * 86400)
        self.assertTrue(self.store.mark_stars_refunded(
            OWNER, "charge_premium_0", now=NOW + 1,
        )[1])
        self.assertEqual(self.store.premium_expiry(OWNER), NOW + 30 * 86400)
        self.assertFalse(self.store.mark_stars_refunded(
            OWNER, "charge_premium_0", now=NOW + 2,
        )[1])
        self.assertEqual(self.store.stars_order(OWNER, first["order_id"])["status"], "refunded")
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER, first["order_id"], now=NOW + 3)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 5)["plan"], "pro")
        self.assertTrue(self.store.mark_stars_refunded(
            OWNER, "charge_premium_1", now=NOW + 10,
        )[1])
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 10)["plan"], "free")

    def test_refund_pack_revokes_unused_balance_and_blocks_replay(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "charge_refund", 19, "XTR", now=NOW)
        self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 10)
        self.assertTrue(self.store.mark_stars_refunded(
            OWNER, "charge_refund", now=NOW + 1,
        )[1])
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 0)
        self.assertEqual(self.store._db.execute(
            "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 0)
        self.assertFalse(self.store.mark_stars_refunded(
            OWNER, "charge_refund", now=NOW + 2,
        )[1])
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW + 3)
        with self.assertRaises(ValueError):
            self.store.record_stars_payment(
                OWNER, order["order_id"], "charge_refund", 19, "XTR", now=NOW + 4,
            )

    def test_refunded_spent_pack_creates_debt_repaid_by_future_grants(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "charge_spent", 19, "XTR", now=NOW)
        self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        for i in range(10):
            op = f"test:daily:{i:012d}"
            self.store.reserve_operation(OWNER, op, now=NOW)
            self.store.settle_operation(OWNER, op, success=True, now=NOW)
        for i in range(4):
            op = f"test:pack:{i:012d}"
            self.assertEqual(self.store.reserve_operation(OWNER, op, now=NOW)["source"], "pack")
            self.store.settle_operation(OWNER, op, success=True, now=NOW)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 6)
        self.store.mark_stars_refunded(OWNER, "charge_spent", now=NOW + 1)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 0)
        self.assertEqual(self.store._db.execute(
            "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 4)
        self.assertEqual(self.store.grant_operation_pack(
            OWNER, 10, "trusted:new:pack:001", now=NOW + 2,
        ), (6, True))
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 6)
        self.assertEqual(self.store._db.execute(
            "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 0)

    def test_refunded_reserved_pack_failure_offsets_debt(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "charge_pending", 19, "XTR", now=NOW)
        self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        for i in range(10):
            op = f"test:all_daily:{i:08d}"
            self.store.reserve_operation(OWNER, op, now=NOW)
        op = "test:pending_pack:0001"
        self.assertEqual(self.store.reserve_operation(OWNER, op, now=NOW)["source"], "pack")
        self.store.mark_stars_refunded(OWNER, "charge_pending", now=NOW + 1)
        self.assertEqual(self.store._db.execute(
            "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 1)
        self.store.settle_operation(OWNER, op, success=False, now=NOW + 2)
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 0)
        self.assertEqual(self.store._db.execute(
            "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 0)

    def test_fulfillment_rolls_back_when_pack_capacity_full_then_retries(self):
        order = self.store.create_stars_order(OWNER, "pack_30", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "charge_capacity", 49, "XTR", now=NOW)
        self.store._db.execute(
            "INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)", (OWNER, 9990),
        )
        with self.assertRaises(ValueError):
            self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)
        self.assertEqual(self.store.stars_order(OWNER, order["order_id"])["status"], "verified")
        self.assertEqual(self.store._db.execute(
            "SELECT COUNT(*) FROM operation_pack_grants WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 0)
        self.store._db.execute(
            "UPDATE operation_pack_balances SET balance=100 WHERE owner_id=?", (OWNER,),
        )
        self.assertTrue(self.store.fulfill_stars_order(OWNER, order["order_id"], now=NOW + 1)[1])
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW + 1)["pack_remaining"], 130)

    def test_concurrent_duplicate_fulfillment_debits_once(self):
        order = self.store.create_stars_order(OWNER, "pack_10", now=NOW)
        self.store.record_stars_payment(OWNER, order["order_id"], "charge_race", 19, "XTR", now=NOW)
        with DurableJobStore(self.path) as second:
            gate = threading.Barrier(2)
            def fulfill(store):
                gate.wait(timeout=5)
                return store.fulfill_stars_order(OWNER, order["order_id"], now=NOW)[1]
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(fulfill, (self.store, second)))
        self.assertCountEqual(outcomes, [True, False])
        self.assertEqual(self.store.usage_snapshot(OWNER, now=NOW)["pack_remaining"], 10)
        self.assertEqual(self.store._db.execute(
            "SELECT COUNT(*) FROM operation_pack_grants WHERE owner_id=?", (OWNER,),
        ).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
