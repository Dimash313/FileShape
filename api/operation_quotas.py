"""Atomic server-side FileShape operation quota ledger.

This is a storage primitive, not a payment or processing admission endpoint.
Only trusted server code may call grant_operation_pack(). Processing endpoints
must not show quotas as enforced until they use claim/refund consistently.
"""
import math
import re
import time

FREE_DAILY_OPERATIONS = 10
PRO_DAILY_OPERATIONS = 100
PACK_PRICES_STARS = {10: 19, 30: 49}
MAX_PACK_BALANCE = 1_000_000
_CLAIM_RE = re.compile(r"[A-Za-z0-9:_-]{16,128}\Z")
_GRANT_RE = re.compile(r"[A-Za-z0-9:_-]{12,160}\Z")


class QuotaExhausted(Exception):
    """Neither the current UTC daily allowance nor purchased credits suffice."""


class QuotaClaimRefunded(Exception):
    """A refunded claim cannot be charged again using the same identifier."""


def _now(value: float | None) -> float:
    if value is None:
        value = time.time()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid quota timestamp")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Invalid quota timestamp")
    return float(value)


def initialize_operation_quota_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_day_usage (
            owner_id INTEGER NOT NULL,
            utc_day INTEGER NOT NULL,
            used INTEGER NOT NULL CHECK(used BETWEEN 0 AND 100),
            PRIMARY KEY(owner_id, utc_day)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_pack_balances (
            owner_id INTEGER PRIMARY KEY,
            remaining INTEGER NOT NULL CHECK(remaining BETWEEN 0 AND 1000000)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_pack_grants (
            grant_key TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            units INTEGER NOT NULL CHECK(units IN (10,30)),
            created_at REAL NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS operation_claims (
            claim_key TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            utc_day INTEGER NOT NULL,
            source TEXT NOT NULL CHECK(source IN ('daily','pack')),
            charged_at REAL NOT NULL,
            refunded_at REAL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_operation_claims_time ON operation_claims(charged_at)")


class OperationQuotaMixin:
    """All mutations use BEGIN IMMEDIATE to serialize *different* SQLite connections."""

    def _quota_tier(self, owner_id, now):
        row = self._db.execute(
            "SELECT expires_at FROM premium_entitlements WHERE owner_id=?",
            (owner_id,),
        ).fetchone()
        expiry = float(row[0]) if row else None
        return ("pro" if expiry is not None and expiry > now else "free"), expiry

    def quota_status(self, owner_id: int, *, now: float | None = None) -> dict:
        """Actual durable counters; not proof that all processing routes enforce quotas."""
        self._validate_owner(owner_id)
        now = _now(now)
        day = int(now // 86400)
        with self._lock:
            tier, expiry = self._quota_tier(owner_id, now)
            limit = PRO_DAILY_OPERATIONS if tier == "pro" else FREE_DAILY_OPERATIONS
            used = self._db.execute(
                "SELECT used FROM operation_day_usage WHERE owner_id=? AND utc_day=?",
                (owner_id, day),
            ).fetchone()
            pack = self._db.execute(
                "SELECT remaining FROM operation_pack_balances WHERE owner_id=?",
                (owner_id,),
            ).fetchone()
        daily_used = int(used[0]) if used else 0
        extras = int(pack[0]) if pack else 0
        return {
            "tier": tier,
            "daily_limit": limit,
            "daily_used": daily_used,
            "daily_remaining": max(0, limit - daily_used),
            "extra_remaining": extras,
            "total_remaining": max(0, limit - daily_used) + extras,
            "reset_at": (day + 1) * 86400,
            "premium_until": expiry,
        }

    def grant_operation_pack(self, owner_id: int, units: int, grant_key: str,
                             *, now: float | None = None) -> tuple[int, bool]:
        """Trusted payment/admin grant ONLY. Caller must verify the Stars receipt.

        The durable idempotency key prevents repeat or cross-account grants.
        This deliberately exposes no public method to claim a purchase.
        """
        self._validate_owner(owner_id)
        if type(units) is not int or units not in PACK_PRICES_STARS:
            raise ValueError("Invalid pack size")
        if not isinstance(grant_key, str) or _GRANT_RE.fullmatch(grant_key) is None:
            raise ValueError("Invalid pack grant key")
        now = _now(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT owner_id,units FROM operation_pack_grants WHERE grant_key=?",
                    (grant_key,),
                ).fetchone()
                if existing:
                    if tuple(existing) != (owner_id, units):
                        raise ValueError("Pack grant conflict")
                    created = False
                else:
                    self._db.execute(
                        """INSERT INTO operation_pack_balances(owner_id,remaining)
                           VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE
                           SET remaining=remaining+excluded.remaining""",
                        (owner_id, units),
                    )
                    self._db.execute(
                        "INSERT INTO operation_pack_grants(grant_key,owner_id,units,created_at) VALUES(?,?,?,?)",
                        (grant_key, owner_id, units, now),
                    )
                    created = True
                row = self._db.execute(
                    "SELECT remaining FROM operation_pack_balances WHERE owner_id=?",
                    (owner_id,),
                ).fetchone()
                self._db.execute("COMMIT")
                return int(row[0]), created
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def claim_operation(self, owner_id: int, claim_key: str, *,
                        now: float | None = None) -> tuple[str, bool]:
        """Charge once per trusted job ID. Daily quota before paid extra credits.

        Returns (source, newly_charged). A duplicate active claim never charges
        again, including after UTC midnight. A refunded claim cannot be reused.
        """
        self._validate_owner(owner_id)
        if not isinstance(claim_key, str) or _CLAIM_RE.fullmatch(claim_key) is None:
            raise ValueError("Invalid claim identifier")
        now = _now(now)
        day = int(now // 86400)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT owner_id,source,refunded_at FROM operation_claims WHERE claim_key=?",
                    (claim_key,),
                ).fetchone()
                if existing:
                    if int(existing[0]) != owner_id:
                        raise ValueError("Operation claim owner conflict")
                    if existing[2] is not None:
                        raise QuotaClaimRefunded()
                    source, charged = str(existing[1]), False
                else:
                    tier, _ = self._quota_tier(owner_id, now)
                    limit = PRO_DAILY_OPERATIONS if tier == "pro" else FREE_DAILY_OPERATIONS
                    row = self._db.execute(
                        "SELECT used FROM operation_day_usage WHERE owner_id=? AND utc_day=?",
                        (owner_id, day),
                    ).fetchone()
                    if (int(row[0]) if row else 0) < limit:
                        self._db.execute(
                            """INSERT INTO operation_day_usage(owner_id,utc_day,used)
                               VALUES(?,?,1) ON CONFLICT(owner_id,utc_day)
                               DO UPDATE SET used=used+1""",
                            (owner_id, day),
                        )
                        source = "daily"
                    else:
                        updated = self._db.execute(
                            """UPDATE operation_pack_balances SET remaining=remaining-1
                               WHERE owner_id=? AND remaining>0""",
                            (owner_id,),
                        )
                        if updated.rowcount != 1:
                            raise QuotaExhausted()
                        source = "pack"
                    self._db.execute(
                        """INSERT INTO operation_claims(claim_key,owner_id,utc_day,source,charged_at)
                           VALUES(?,?,?,?,?)""",
                        (claim_key, owner_id, day, source, now),
                    )
                    charged = True
                self._db.execute("COMMIT")
                return source, charged
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def refund_operation(self, owner_id: int, claim_key: str,
                         *, now: float | None = None) -> bool:
        """Idempotent rollback after rejected/failed work, on the ORIGINAL UTC day."""
        self._validate_owner(owner_id)
        if not isinstance(claim_key, str) or _CLAIM_RE.fullmatch(claim_key) is None:
            raise ValueError("Invalid claim identifier")
        now = _now(now)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT owner_id,utc_day,source,refunded_at FROM operation_claims WHERE claim_key=?",
                    (claim_key,),
                ).fetchone()
                if row is None:
                    changed = False
                elif int(row[0]) != owner_id:
                    raise ValueError("Operation refund owner conflict")
                elif row[3] is not None:
                    changed = False
                else:
                    if row[2] == "daily":
                        result = self._db.execute(
                            """UPDATE operation_day_usage SET used=used-1
                               WHERE owner_id=? AND utc_day=? AND used>0""",
                            (owner_id, row[1]),
                        )
                    else:
                        result = self._db.execute(
                            """UPDATE operation_pack_balances SET remaining=remaining+1
                               WHERE owner_id=? AND remaining<1000000""",
                            (owner_id,),
                        )
                    if result.rowcount != 1:
                        raise RuntimeError("Operation quota ledger inconsistent")
                    self._db.execute(
                        "UPDATE operation_claims SET refunded_at=? WHERE claim_key=?",
                        (now, claim_key),
                    )
                    changed = True
                self._db.execute("COMMIT")
                return changed
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def prune_operation_quotas(self, *, now: float | None = None,
                               retention_days: int = 90) -> tuple[int, int]:
        """Delete old daily usage/claim receipts, retain purchase grant IDs forever.

        A retained grant ID is necessary to prevent a replayed payment granting
        credits again; it stores no file content or payment credentials.
        """
        now = _now(now)
        if type(retention_days) is not int or not 30 <= retention_days <= 365:
            raise ValueError("Invalid quota retention")
        cutoff_day = int(now // 86400) - retention_days
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                claims = self._db.execute(
                    "DELETE FROM operation_claims WHERE utc_day<?",
                    (cutoff_day,),
                ).rowcount
                days = self._db.execute(
                    "DELETE FROM operation_day_usage WHERE utc_day<?",
                    (cutoff_day,),
                ).rowcount
                self._db.execute("COMMIT")
                return claims, days
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
