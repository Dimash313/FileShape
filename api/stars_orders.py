"""Private durable Stars order registry. No checkout/payment activation.

Only Telegram-received successful_payment claims may eventually reach the
trusted bridge. This module stores exact orders and deduplicates charge IDs;
it deliberately does NOT grant Pro, add pack balance, or create invoices.
"""
import math
import re
import secrets
import sqlite3
import time

ORDER_TTL_SECONDS = 30 * 60
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
            CHECK (
              (status = 'pending' AND telegram_charge_id IS NULL AND verified_at IS NULL)
              OR (status != 'pending' AND telegram_charge_id IS NOT NULL AND verified_at IS NOT NULL)
            )
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_stars_orders_owner ON stars_orders(owner_id,created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_stars_orders_status ON stars_orders(status,created_at)")


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
                self._db.execute(
                    """INSERT INTO stars_orders
                       (order_id,owner_id,sku,amount,currency,status,created_at,expires_at)
                       VALUES(?,?,?,?,?,'pending',?,?)""",
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
        """Deny unknown/expired/paid quotes before approving a Telegram checkout."""
        self._validate_owner(owner_id)
        _order_id(order_id)
        _payment_amount(amount, currency)
        now = _time(now)
        with self._lock:
            row = self._db.execute(
                """SELECT amount,currency,status,expires_at FROM stars_orders
                   WHERE order_id=? AND owner_id=?""", (order_id, owner_id),
            ).fetchone()
        return bool(row and row[0] == amount and row[1] == currency
                    and row[2] == "pending" and now <= float(row[3]))

    def record_stars_payment(self, owner_id: int, order_id: str, charge_id: str,
                             amount: int, currency: str, *, now=None):
        """Persist a trusted successful_payment claim exactly once.

        Only a later signed Telegram update bridge may invoke this method.
        This method intentionally does not fulfill paid entitlements yet.
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
