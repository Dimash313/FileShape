"""Durable, atomic Free/Pro operation allowances and prepaid operation packs.

Foundation only: do NOT expose a public grant endpoint or claim that processing
is metered until each admission path is wired to reserve/settle.
No payment verification is performed here. Only trusted server code may grant.
"""
from datetime import datetime, timezone
import math
import re
import time

FREE_DAILY_OPERATIONS = 10
PRO_DAILY_OPERATIONS = 100
MAX_PACK_BALANCE = 10000
_KEY = re.compile(r"[A-Za-z0-9:_-]{12,160}\Z")


class OperationQuotaExceeded(Exception):
    """No daily operations and no prepaid operations remain."""


def _timestamp(now):
    if now is None:
        now = time.time()
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        raise ValueError("Invalid timestamp")
    if not math.isfinite(now) or now <= 0 or now > 253402300799:
        raise ValueError("Invalid timestamp")
    return float(now)


def _key(value):
    if not isinstance(value, str) or _KEY.fullmatch(value) is None:
        raise ValueError("Invalid idempotency key")
    return value


def _day(now):
    return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()


def initialize_usage_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_pack_balances (
            owner_id INTEGER PRIMARY KEY CHECK (owner_id > 0),
            balance INTEGER NOT NULL CHECK (balance >= 0 AND balance <= 10000)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_pack_grants (
            grant_key TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL CHECK (owner_id > 0),
            operations INTEGER NOT NULL CHECK (operations IN (10, 30)),
            granted_at REAL NOT NULL,
            resulting_balance INTEGER NOT NULL CHECK (resulting_balance >= 0)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_usage (
            operation_key TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL CHECK (owner_id > 0),
            day_utc TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('daily','pack')),
            status TEXT NOT NULL CHECK (status IN ('reserved','committed','released')),
            created_at REAL NOT NULL,
            settled_at REAL
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_operation_usage_owner_day
        ON operation_usage(owner_id, day_utc, source, status)
    """)


class UsageQuotaMixin:
    def _usage_state(self, owner_id, now):
        row = self._db.execute(
            "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
            (owner_id,),
        ).fetchone()
        is_pro = row is not None and float(row[0]) > now
        day = _day(now)
        limit = PRO_DAILY_OPERATIONS if is_pro else FREE_DAILY_OPERATIONS
        used = self._db.execute(
            """SELECT COUNT(*) FROM operation_usage WHERE owner_id=? AND day_utc=?
               AND source='daily' AND status IN ('reserved','committed')""",
            (owner_id, day),
        ).fetchone()[0]
        row = self._db.execute(
            "SELECT balance FROM operation_pack_balances WHERE owner_id=?",
            (owner_id,),
        ).fetchone()
        balance = 0 if row is None else int(row[0])
        return {
            "plan": "pro" if is_pro else "free",
            "day_utc": day,
            "daily_limit": limit,
            "daily_used": used,
            "daily_remaining": max(0, limit - used),
            "pack_remaining": balance,
            "pro_expires_at": None,
        }

    def usage_snapshot(self, owner_id, *, now=None):
        """Read trusted persisted usage. Reservations count until settled/released."""
        self._validate_owner(owner_id)
        now = _timestamp(now)
        with self._lock:
            state = self._usage_state(owner_id, now)
            expiry = self._db.execute(
                "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
                (owner_id,),
            ).fetchone()
            state["pro_expires_at"] = float(expiry[0]) if expiry and expiry[0] > now else None
            return state

    def grant_operation_pack(self, owner_id, operations, grant_key, *, now=None):
        """Trust-boundary primitive: idempotent trusted grants, not a checkout API."""
        self._validate_owner(owner_id)
        if type(operations) is not int or operations not in (10, 30):
            raise ValueError("Invalid pack size")
        _key(grant_key)
        now = _timestamp(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT owner_id,operations,resulting_balance FROM operation_pack_grants WHERE grant_key=?",
                    (grant_key,),
                ).fetchone()
                if existing:
                    if existing[0] != owner_id or existing[1] != operations:
                        raise ValueError("Pack grant idempotency conflict")
                    result = (int(existing[2]), False)
                else:
                    row = self._db.execute(
                        "SELECT balance FROM operation_pack_balances WHERE owner_id=?",
                        (owner_id,),
                    ).fetchone()
                    balance = (int(row[0]) if row else 0) + operations
                    # Outstanding pack-backed operations can still fail and be
                    # refunded. Reserve room for their eventual return.
                    pending = self._db.execute(
                        """SELECT COUNT(*) FROM operation_usage
                           WHERE owner_id=? AND source='pack' AND status='reserved'""",
                        (owner_id,),
                    ).fetchone()[0]
                    if balance + pending > MAX_PACK_BALANCE:
                        raise ValueError("Pack balance limit")
                    self._db.execute(
                        """INSERT INTO operation_pack_balances(owner_id,balance) VALUES(?,?)
                           ON CONFLICT(owner_id) DO UPDATE SET balance=excluded.balance""",
                        (owner_id, balance),
                    )
                    self._db.execute(
                        """INSERT INTO operation_pack_grants
                           (grant_key,owner_id,operations,granted_at,resulting_balance)
                           VALUES(?,?,?,?,?)""",
                        (grant_key, owner_id, operations, now, balance),
                    )
                    result = (balance, True)
                self._db.execute("COMMIT")
                return result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _reserve_operation_in_transaction(self, owner_id, operation_key, now):
        """Use inside a caller-owned BEGIN IMMEDIATE transaction."""
        prior = self._db.execute(
            "SELECT owner_id,day_utc,source,status FROM operation_usage WHERE operation_key=?",
            (operation_key,),
        ).fetchone()
        if prior:
            if prior[0] != owner_id:
                raise PermissionError("Operation belongs to another owner")
            return {"day_utc": prior[1], "source": prior[2], "status": prior[3], "created": False}
        state = self._usage_state(owner_id, now)
        if state["daily_remaining"] > 0:
            source = "daily"
        elif state["pack_remaining"] > 0:
            source = "pack"
            changed = self._db.execute(
                """UPDATE operation_pack_balances SET balance=balance-1
                   WHERE owner_id=? AND balance>0""",
                (owner_id,),
            ).rowcount
            if changed != 1:
                raise OperationQuotaExceeded()
        else:
            raise OperationQuotaExceeded()
        self._db.execute(
            """INSERT INTO operation_usage
               (operation_key,owner_id,day_utc,source,status,created_at)
               VALUES(?,?,?,?,'reserved',?)""",
            (operation_key, owner_id, state["day_utc"], source, now),
        )
        return {"day_utc": state["day_utc"], "source": source, "status": "reserved", "created": True}

    def reserve_operation(self, owner_id, operation_key, *, now=None):
        """Atomically reserve one operation across concurrent SQLite connections.

        operation_key MUST be server-generated for an accepted operation; never
        pass an untrusted client idempotency key straight through.
        """
        self._validate_owner(owner_id)
        _key(operation_key)
        now = _timestamp(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                result = self._reserve_operation_in_transaction(owner_id, operation_key, now)
                self._db.execute("COMMIT")
                return result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _settle_operation_in_transaction(self, owner_id, operation_key, success, now):
        """Settle in the same SQLite transaction as the owning job transition."""
        row = self._db.execute(
            "SELECT owner_id,source,status FROM operation_usage WHERE operation_key=?",
            (operation_key,),
        ).fetchone()
        if row is None:
            raise LookupError("Operation not found")
        if row[0] != owner_id:
            raise PermissionError("Operation belongs to another owner")
        status = "committed" if success else "released"
        if row[2] != "reserved":
            if row[2] != status:
                raise ValueError("Conflicting settlement")
            return False
        self._db.execute(
            "UPDATE operation_usage SET status=?,settled_at=? WHERE operation_key=?",
            (status, now, operation_key),
        )
        if row[1] == "pack" and not success:
            self._db.execute(
                "UPDATE operation_pack_balances SET balance=balance+1 WHERE owner_id=?",
                (owner_id,),
            )
        return True

    def settle_operation(self, owner_id, operation_key, *, success, now=None):
        """Commit a successful operation or release a failed reservation.

        Replaying the same decision is safe; opposing decisions fail closed.
        """
        self._validate_owner(owner_id)
        _key(operation_key)
        if type(success) is not bool:
            raise ValueError("Invalid settlement")
        now = _timestamp(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                changed = self._settle_operation_in_transaction(owner_id, operation_key, success, now)
                self._db.execute("COMMIT")
                return changed
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
