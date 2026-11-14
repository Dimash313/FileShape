"""Private durable Stars order registry and exactly-once accounting.

Only trusted Telegram successful_payment forwarding may verify an invoice.
An atomic SQLite transaction fulfills verified receipts into Pro or pack
entitlements; pending invoices never grant paid access.
"""
import math
import re
import secrets
import sqlite3
import time

ORDER_TTL_SECONDS = 30 * 60
MAX_ACTIVE_QUOTES_PER_OWNER = 5
UNPAID_RETENTION_SECONDS = 14 * 86400
STARS_CURRENCY = "XTR"
PRODUCTS = {
    "pro_30d": {"amount": 149, "duration_seconds": 30 * 86400},
    "pack_10": {"amount": 19, "operations": 10},
    "pack_30": {"amount": 49, "operations": 30},
}
_ORDER_ID = re.compile(r"[0-9a-f]{32}\Z")


def _time(value):
    if value is None:
        value = time.time()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid payment timestamp")
    if not math.isfinite(value) or value <= 0 or value > 253402300799:
        raise ValueError("Invalid payment timestamp")
    return float(value)


def _charge(value):
    # Telegram's opaque charge ID must be persisted for official refunds.
    # No invented card details, address, raw file data or customer names.
    if (not isinstance(value, str) or not 1 <= len(value) <= 256
            or not value.isascii() or any(ord(ch) < 33 or ord(ch) > 126 for ch in value)):
        raise ValueError("Invalid Telegram payment charge ID")
    return value


def _order_id(value):
    if not isinstance(value, str) or _ORDER_ID.fullmatch(value) is None:
        raise ValueError("Invalid order ID")
    return value


def _payment_amount(amount, currency):
    if type(amount) is not int or amount <= 0 or currency != STARS_CURRENCY:
        raise ValueError("Invalid payment currency or amount")


def initialize_stars_order_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS stars_orders (
            order_id TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL CHECK(owner_id > 0),
            sku TEXT NOT NULL CHECK(sku IN ('pro_30d','pack_10','pack_30')),
            amount INTEGER NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL CHECK(currency = 'XTR'),
            status TEXT NOT NULL CHECK(status IN ('pending','verified','fulfilled','refunded')),
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            telegram_charge_id TEXT UNIQUE,
            verified_at REAL,
            fulfilled_at REAL,
            refunded_at REAL,
            -- Legacy rows are conservatively treated as potentially checked out.
            -- New, never-approved quotes may be pruned after retention.
            never_prechecked INTEGER NOT NULL DEFAULT 0 CHECK (never_prechecked IN (0,1)),
            CHECK (
              (status = 'pending' AND telegram_charge_id IS NULL AND verified_at IS NULL)
              OR (status != 'pending' AND telegram_charge_id IS NOT NULL AND verified_at IS NOT NULL)
            )
        )
    """)
    # Existing installations may have approved invoices before this column
    # existed. DEFAULT 0 protects all such legacy quotes from deletion.
    columns = {row[1] for row in db.execute("PRAGMA table_info(stars_orders)")}
    if "never_prechecked" not in columns:
        db.execute(
            "ALTER TABLE stars_orders ADD COLUMN never_prechecked INTEGER "
            "NOT NULL DEFAULT 0 CHECK (never_prechecked IN (0,1))"
        )
    db.execute("CREATE INDEX IF NOT EXISTS idx_stars_orders_owner ON stars_orders(owner_id,created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_stars_orders_status ON stars_orders(status,created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_stars_orders_expiry ON stars_orders(status,expires_at)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS stars_pack_debts (
            owner_id INTEGER PRIMARY KEY CHECK (owner_id > 0),
            debt INTEGER NOT NULL CHECK (debt >= 0)
        )
    """)


def _public(row):
    return {
        "order_id": row[0], "sku": row[1], "amount": int(row[2]),
        "currency": row[3], "status": row[4],
        "created_at": float(row[5]), "expires_at": float(row[6]),
    }


class StarsOrderMixin:
    def create_stars_order(self, owner_id: int, sku: str, *, now=None):
        """Owner-bound immutable catalog quote; never grants entitlements."""
        self._validate_owner(owner_id)
        if not isinstance(sku, str) or sku not in PRODUCTS:
            raise ValueError("Unknown Stars product")
        now = _time(now)
        order_id = secrets.token_hex(16)
        amount = PRODUCTS[sku]["amount"]
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                count = self._db.execute(
                    """SELECT COUNT(*) FROM stars_orders
                       WHERE owner_id=? AND status='pending' AND expires_at>?""",
                    (owner_id, now),
                ).fetchone()[0]
                if count >= MAX_ACTIVE_QUOTES_PER_OWNER:
                    raise ValueError("Too many active unpaid Stars orders")
                self._db.execute(
                    """INSERT INTO stars_orders
                       (order_id,owner_id,sku,amount,currency,status,created_at,expires_at,never_prechecked)
                       VALUES(?,?,?,?,?,'pending',?,?,1)""",
                    (order_id, owner_id, sku, amount, STARS_CURRENCY, now, now + ORDER_TTL_SECONDS),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return {
            "order_id": order_id, "sku": sku, "amount": amount,
            "currency": STARS_CURRENCY, "status": "pending",
            "created_at": now, "expires_at": now + ORDER_TTL_SECONDS,
        }

    def stars_order(self, owner_id: int, order_id: str):
        """Private read by authenticated owner, no charge IDs in response."""
        self._validate_owner(owner_id)
        _order_id(order_id)
        with self._lock:
            row = self._db.execute(
                """SELECT order_id,sku,amount,currency,status,created_at,expires_at
                   FROM stars_orders WHERE order_id=? AND owner_id=?""",
                (order_id, owner_id),
            ).fetchone()
        return None if row is None else _public(row)

    def can_precheckout_stars_order(self, owner_id: int, order_id: str, amount: int,
                                   currency: str, *, now=None) -> bool:
        """Approve only an exact invoice, persisting its non-prunable status.

        Pack invoices reserve possible future balance before a positive
        precheckout answer; a paid order must not be rejected solely because
        multiple unfulfilled invoices filled available pack capacity.
        A successful Telegram pre_checkout_query may be charged even if the
        API or bot crashes before seeing successful_payment. The reservation
        against automatic quote deletion MUST commit before replying True.
        """
        self._validate_owner(owner_id)
        _order_id(order_id)
        _payment_amount(amount, currency)
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT sku,amount,currency,status,expires_at,never_prechecked
                       FROM stars_orders WHERE order_id=? AND owner_id=?""",
                    (order_id, owner_id),
                ).fetchone()
                approved = bool(row and row[1] == amount and row[2] == currency
                                and row[3] == "pending" and now <= float(row[4]))
                if approved and row[0] in ("pack_10", "pack_30") and row[5] == 1:
                    # A previously approved invoice may settle long after
                    # its pre-checkout expiry. Reserve enough capacity for
                    # every such pending invoice, not just the active quote.
                    balance_row = self._db.execute(
                        "SELECT balance FROM operation_pack_balances WHERE owner_id=?",
                        (owner_id,),
                    ).fetchone()
                    balance = int(balance_row[0]) if balance_row else 0
                    outstanding = self._db.execute(
                        """SELECT COUNT(*) FROM operation_usage
                           WHERE owner_id=? AND source='pack' AND status='reserved'""",
                        (owner_id,),
                    ).fetchone()[0]
                    approved_pending = self._db.execute(
                        """SELECT COALESCE(SUM(CASE sku
                           WHEN 'pack_10' THEN 10 WHEN 'pack_30' THEN 30
                           ELSE 0 END),0)
                           FROM stars_orders WHERE owner_id=? AND status='pending'
                           AND never_prechecked=0 AND sku IN ('pack_10','pack_30')""",
                        (owner_id,),
                    ).fetchone()[0]
                    incoming = PRODUCTS[row[0]]["operations"]
                    if balance + outstanding + approved_pending + incoming > 10000:
                        approved = False
                if approved:
                    self._db.execute(
                        """UPDATE stars_orders SET never_prechecked=0
                           WHERE order_id=? AND owner_id=?""",
                        (order_id, owner_id),
                    )
                self._db.execute("COMMIT")
                return approved
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def record_stars_payment(self, owner_id: int, order_id: str, charge_id: str,
                             amount: int, currency: str, *, now=None):
        """Persist a trusted Telegram successful_payment claim exactly once.

        This operation verifies the order; fulfillment is a separate atomic
        transaction that can be retried after process crashes.
        """
        self._validate_owner(owner_id)
        _order_id(order_id)
        _charge(charge_id)
        _payment_amount(amount, currency)
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT sku,amount,currency,status,telegram_charge_id
                       FROM stars_orders WHERE order_id=? AND owner_id=?""",
                    (order_id, owner_id),
                ).fetchone()
                if row is None or row[1] != amount or row[2] != currency:
                    raise ValueError("Stars order ownership or invoice mismatch")
                if row[3] in ("verified", "fulfilled") and row[4] == charge_id:
                    created = False
                elif row[3] != "pending":
                    raise ValueError("Conflicting Telegram Stars payment")
                else:
                    try:
                        changed = self._db.execute(
                            """UPDATE stars_orders
                               SET status='verified',telegram_charge_id=?,verified_at=?
                               WHERE order_id=? AND owner_id=? AND status='pending'""",
                            (charge_id, now, order_id, owner_id),
                        ).rowcount
                    except sqlite3.IntegrityError:
                        raise ValueError("Telegram charge ID was used for another order") from None
                    if changed != 1:
                        raise ValueError("Stars payment transition conflict")
                    created = True
                self._db.execute("COMMIT")
                return {"order_id": order_id, "sku": row[0], "status": "verified" if created else row[3]}, created
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def fulfill_stars_order(self, owner_id: int, order_id: str, *, now=None):
        """Exactly-once fulfilment in the *same* SQLite write as the order state.

        Called exclusively by a trusted successful_payment bridge, never from
        pre_checkout_query or an untrusted Mini App callback.
        """
        self._validate_owner(owner_id)
        _order_id(order_id)
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT sku,status,telegram_charge_id
                       FROM stars_orders WHERE order_id=? AND owner_id=?""",
                    (order_id, owner_id),
                ).fetchone()
                if row is None or row[1] not in ("verified", "fulfilled") or not row[2]:
                    raise ValueError("Order not verified by Telegram")
                sku, status, charge_id = row
                if status == "fulfilled":
                    self._db.execute("COMMIT")
                    return {"order_id": order_id, "sku": sku, "status": "fulfilled"}, False
                product = PRODUCTS[sku]
                grant_key = "stars:order:" + order_id
                if sku == "pro_30d":
                    if self._db.execute(
                        "SELECT 1 FROM premium_grants WHERE grant_key=?", (grant_key,)
                    ).fetchone():
                        raise ValueError("Unexpected duplicate premium grant")
                    existing = self._db.execute(
                        "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
                        (owner_id,),
                    ).fetchone()
                    base = max(now, float(existing[0])) if existing else now
                    expiry = base + product["duration_seconds"]
                    self._db.execute(
                        """INSERT INTO premium_entitlements(owner_id,expires_at) VALUES(?,?)
                           ON CONFLICT(owner_id) DO UPDATE SET expires_at=excluded.expires_at""",
                        (owner_id, expiry),
                    )
                    self._db.execute(
                        """INSERT INTO premium_grants(grant_key,owner_id,seconds,granted_at,resulting_expiry)
                           VALUES(?,?,?,?,?)""",
                        (grant_key, owner_id, product["duration_seconds"], now, expiry),
                    )
                else:
                    if self._db.execute(
                        "SELECT 1 FROM operation_pack_grants WHERE grant_key=?", (grant_key,)
                    ).fetchone():
                        raise ValueError("Unexpected duplicate operation grant")
                    count = product["operations"]
                    current = self._db.execute(
                        "SELECT balance FROM operation_pack_balances WHERE owner_id=?",
                        (owner_id,),
                    ).fetchone()
                    balance = int(current[0]) if current else 0
                    outstanding = self._db.execute(
                        """SELECT COUNT(*) FROM operation_usage
                           WHERE owner_id=? AND source='pack' AND status='reserved'""",
                        (owner_id,),
                    ).fetchone()[0]
                    debts = self._db.execute(
                        "SELECT debt FROM stars_pack_debts WHERE owner_id=?", (owner_id,)
                    ).fetchone()
                    debt = int(debts[0]) if debts else 0
                    covered = min(count, debt)
                    debt -= covered
                    balance += count - covered
                    if balance + outstanding > 10000:
                        raise ValueError("Pack balance limit with outstanding refunds")
                    self._db.execute(
                        """INSERT INTO stars_pack_debts(owner_id,debt) VALUES(?,?)
                           ON CONFLICT(owner_id) DO UPDATE SET debt=excluded.debt""",
                        (owner_id, debt),
                    )
                    self._db.execute(
                        """INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)
                           ON CONFLICT(owner_id) DO UPDATE SET balance=excluded.balance""",
                        (owner_id, balance),
                    )
                    self._db.execute(
                        """INSERT INTO operation_pack_grants
                           (grant_key,owner_id,operations,granted_at,resulting_balance)
                           VALUES(?,?,?,?,?)""",
                        (grant_key, owner_id, count, now, balance),
                    )
                changed = self._db.execute(
                    """UPDATE stars_orders SET status='fulfilled',fulfilled_at=?
                       WHERE owner_id=? AND order_id=? AND status='verified'""",
                    (now, owner_id, order_id),
                ).rowcount
                if changed != 1:
                    raise ValueError("Stars fulfillment state conflict")
                self._db.execute("COMMIT")
                return {"order_id": order_id, "sku": sku, "status": "fulfilled"}, True
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def record_paid_and_refunded_stars_order(
        self, owner_id: int, order_id: str, charge_id: str,
        amount: int, currency: str, *, now=None,
    ):
        """Record BOTH authoritative Telegram transactions without a temporary grant.

        This is for transaction-history recovery only, when Telegram reports
        an incoming invoice and its matching outgoing refund for the same
        buyer, charge ID and full XTR amount. Pending -> refunded is one
        SQLite write and cannot be raced by automatic fulfillment.
        """
        self._validate_owner(owner_id)
        _order_id(order_id)
        _charge(charge_id)
        _payment_amount(amount, currency)
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT sku,amount,currency,status,telegram_charge_id
                       FROM stars_orders WHERE owner_id=? AND order_id=?""",
                    (owner_id, order_id),
                ).fetchone()
                if row is None or row[1] != amount or row[2] != currency:
                    raise ValueError("Invoice, buyer or refunded Stars amount mismatch")
                sku, _, _, status, prior_charge = row
                if status == "pending":
                    try:
                        updated = self._db.execute(
                            """UPDATE stars_orders SET
                               status='refunded', telegram_charge_id=?,
                               verified_at=?,refunded_at=?
                               WHERE owner_id=? AND order_id=? AND status='pending'""",
                            (charge_id, now, now, owner_id, order_id),
                        ).rowcount
                    except sqlite3.IntegrityError:
                        raise ValueError("Telegram charge ID used by another order") from None
                    if updated != 1:
                        raise ValueError("Stars refund transition conflict")
                    result = {"order_id": order_id, "sku": sku, "status": "refunded"}
                    created = True
                elif prior_charge != charge_id:
                    raise ValueError("Conflicting charge ID for refunded order")
                else:
                    # Existing verified/fulfilled orders still require
                    # entitlement reversal by mark_stars_refunded().
                    result = {"order_id": order_id, "sku": sku, "status": status}
                    created = False
                self._db.execute("COMMIT")
                return result, created
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def prune_expired_stars_quotes(self, *, limit: int = 100, now=None) -> int:
        """Remove only provably never-approved, long-expired quotes.

        A pending invoice can be paid even if Telegram's success event has not
        reached our API. Such orders and all legacy orders are retained.
        """
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid Stars quote pruning limit")
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                changed = self._db.execute(
                    """DELETE FROM stars_orders WHERE order_id IN (
                         SELECT order_id FROM stars_orders
                         WHERE status='pending' AND never_prechecked=1
                           AND expires_at<?
                         ORDER BY expires_at LIMIT ?
                       )""",
                    (now - UNPAID_RETENTION_SECONDS, limit),
                ).rowcount
                self._db.execute("COMMIT")
                return changed
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def reconcile_verified_stars_orders(self, *, limit: int = 20) -> int:
        """Retry only persisted Telegram-confirmed receipts after a crash.

        No grant can be created from a pending invoice. Each fulfillment uses
        a new atomic transaction and can be safely replayed.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid Stars reconciliation limit")
        with self._lock:
            rows = self._db.execute(
                """SELECT owner_id,order_id FROM stars_orders
                   WHERE status='verified' ORDER BY verified_at,order_id LIMIT ?""",
                (limit,),
            ).fetchall()
        fulfilled = 0
        for owner_id, order_id in rows:
            # A single oversized or temporarily inconsistent paid order must
            # not prevent attempts for other buyers.
            try:
                _, created = self.fulfill_stars_order(owner_id, order_id)
            except (ValueError, sqlite3.Error):
                continue
            fulfilled += int(created)
        return fulfilled

    def mark_stars_refunded(self, owner_id: int, charge_id: str, *, now=None):
        """Apply a verified Telegram refund *after* Telegram reports success.

        Unspent pack credit is revoked; the remainder becomes non-spendable
        debt, deducted from future pack grants/pack-job refunds. For Pro,
        retract up to the duration from any remaining entitlement time.
        A failed refund API call must never invoke this method.
        """
        self._validate_owner(owner_id)
        _charge(charge_id)
        now = _time(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT order_id,sku,status FROM stars_orders
                       WHERE owner_id=? AND telegram_charge_id=?""",
                    (owner_id, charge_id),
                ).fetchone()
                if row is None:
                    raise ValueError("Unknown payment charge")
                order_id, sku, status = row
                if status == "refunded":
                    self._db.execute("COMMIT")
                    return {"order_id": order_id, "sku": sku, "status": "refunded"}, False
                if status not in ("verified", "fulfilled"):
                    raise ValueError("Refund order not verified")
                if status == "fulfilled":
                    product = PRODUCTS[sku]
                    if sku == "pro_30d":
                        current = self._db.execute(
                            "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
                            (owner_id,),
                        ).fetchone()
                        if current is None:
                            raise ValueError("Missing granted premium entitlement")
                        expiry = max(now, float(current[0]) - product["duration_seconds"])
                        self._db.execute(
                            "UPDATE premium_entitlements SET expires_at=? WHERE owner_id=?",
                            (expiry, owner_id),
                        )
                    else:
                        available = self._db.execute(
                            "SELECT balance FROM operation_pack_balances WHERE owner_id=?",
                            (owner_id,),
                        ).fetchone()
                        balance = int(available[0]) if available else 0
                        count = product["operations"]
                        remaining = max(0, balance - count)
                        unrecouped = max(0, count - balance)
                        self._db.execute(
                            """INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)
                               ON CONFLICT(owner_id) DO UPDATE SET balance=excluded.balance""",
                            (owner_id, remaining),
                        )
                        self._db.execute(
                            """INSERT INTO stars_pack_debts(owner_id,debt) VALUES(?,?)
                               ON CONFLICT(owner_id) DO UPDATE SET debt=debt+excluded.debt""",
                            (owner_id, unrecouped),
                        )
                changed = self._db.execute(
                    """UPDATE stars_orders SET status='refunded',refunded_at=?
                       WHERE order_id=? AND owner_id=? AND status=?""",
                    (now, order_id, owner_id, status),
                ).rowcount
                if changed != 1:
                    raise ValueError("Stars refund state conflict")
                self._db.execute("COMMIT")
                return {"order_id": order_id, "sku": sku, "status": "refunded"}, True
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
