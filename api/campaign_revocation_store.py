"""Durable, privacy-minimal invite revocation queue.

A terminal campaign and its pending revocation are committed atomically in
the same SQLite transaction. A successful Telegram API response is the only
reason to mark a link revoked. Failures use bounded retry backoff.
"""
import math
import sqlite3
import threading
import time
from functools import wraps


def serialized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def _now(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Invalid revocation timestamp")
    return float(value)


def initialize_campaign_revocations(db: sqlite3.Connection):
    db.execute("""
        CREATE TABLE IF NOT EXISTS ad_campaign_revocations (
            campaign_id TEXT PRIMARY KEY REFERENCES ad_campaigns(campaign_id) ON DELETE CASCADE,
            chat_id INTEGER NOT NULL,
            invite_link TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending','revoked')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            next_attempt_at REAL NOT NULL DEFAULT 0,
            revoked_at REAL,
            CHECK ((state='pending' AND revoked_at IS NULL)
                OR (state='revoked' AND revoked_at IS NOT NULL))
        )
    """)
    db.execute("""CREATE INDEX IF NOT EXISTS idx_campaign_revocations_due
                  ON ad_campaign_revocations(state,next_attempt_at)""")
    # Repair campaigns already completed in older schema versions. Do not
    # claim their links were revoked without a Telegram acknowledgement.
    enqueue_terminal_revocations(db)


def queue_campaign_revocation(db, campaign_id, chat_id, invite_link):
    """Call inside the transaction that closes a campaign."""
    if invite_link is not None:
        db.execute("""
            INSERT OR IGNORE INTO ad_campaign_revocations(
                campaign_id,chat_id,invite_link,state)
            VALUES(?,?,?,'pending')
        """, (campaign_id, chat_id, invite_link))


def enqueue_terminal_revocations(db):
    """Idempotent backfill for both migrated and recently closed campaigns."""
    db.execute("""
        INSERT OR IGNORE INTO ad_campaign_revocations(
            campaign_id,chat_id,invite_link,state)
        SELECT campaign_id,chat_id,invite_link,'pending'
        FROM ad_campaigns
        WHERE state IN ('stopped','completed') AND invite_link IS NOT NULL
    """)


class CampaignRevocationsMixin:
    @serialized
    def pending_campaign_revocations(self, *, now=None, limit=10):
        now = _now(time.time() if now is None else now)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid revocation batch size")
        rows = self._db.execute("""
            SELECT r.campaign_id,r.chat_id,r.invite_link,r.attempts
            FROM ad_campaign_revocations AS r
            JOIN ad_campaigns AS c ON c.campaign_id=r.campaign_id
            WHERE r.state='pending' AND r.next_attempt_at<=?
                  AND c.state IN ('stopped','completed')
            ORDER BY r.next_attempt_at,r.campaign_id LIMIT ?
        """, (now, limit)).fetchall()
        return [
            dict(zip(("campaign_id","chat_id","invite_link","attempts"), row))
            for row in rows
        ]

    @serialized
    def record_campaign_revoked(self, *, campaign_id, chat_id, invite_link, now=None):
        now = _now(time.time() if now is None else now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            changed = self._db.execute("""
                UPDATE ad_campaign_revocations SET state='revoked',revoked_at=?
                WHERE campaign_id=? AND chat_id=? AND invite_link=? AND state='pending'
                  AND EXISTS(
                      SELECT 1 FROM ad_campaigns WHERE campaign_id=?
                          AND state IN ('stopped','completed'))
            """, (now, campaign_id, chat_id, invite_link, campaign_id)).rowcount
            self._db.execute("COMMIT")
            return changed == 1
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @serialized
    def record_campaign_revocation_failure(
        self, *, campaign_id, chat_id, invite_link, now=None
    ):
        now = _now(time.time() if now is None else now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute("""
                SELECT attempts FROM ad_campaign_revocations
                WHERE campaign_id=? AND chat_id=? AND invite_link=? AND state='pending'
            """, (campaign_id, chat_id, invite_link)).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return False
            attempts = min(row[0] + 1, 1_000_000)
            delay = min(3600, 60 * (2 ** min(attempts - 1, 6)))
            self._db.execute("""
                UPDATE ad_campaign_revocations
                SET attempts=?,next_attempt_at=?
                WHERE campaign_id=? AND state='pending'
            """, (attempts, now + delay, campaign_id))
            self._db.execute("COMMIT")
            return True
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
