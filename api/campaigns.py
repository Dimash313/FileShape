"""Owner-controlled ad campaigns and confirmed-join ledger.

This module deliberately does not create Telegram invite links or claim to
observe membership events. Only verified events supplied by a trusted future
Telegram chat_member adapter may be recorded. Raw Telegram user IDs are never
stored: the adapter must supply a keyed SHA-256/HMAC digest per user.
"""
import math
import re
import secrets
import sqlite3
import time

from functools import wraps


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CAMPAIGN = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
_MODES = {"duration", "joins"}
_STATES = {"draft", "active", "paused", "completed", "stopped"}


def _timestamp(value, *, label="timestamp"):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"Invalid {label}")
    return float(value)


def initialize_campaign_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS ad_campaigns (
            campaign_id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('duration','joins')),
            target_joins INTEGER,
            starts_at REAL NOT NULL,
            ends_at REAL NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('draft','active','paused','completed','stopped')),
            invite_link TEXT UNIQUE,
            confirmed_joins INTEGER NOT NULL DEFAULT 0 CHECK(confirmed_joins >= 0),
            created_at REAL NOT NULL,
            CHECK(ends_at > starts_at),
            CHECK((mode='duration' AND target_joins IS NULL)
                OR (mode='joins' AND target_joins > 0))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ad_campaign_joins (
            campaign_id TEXT NOT NULL REFERENCES ad_campaigns(campaign_id) ON DELETE CASCADE,
            user_digest TEXT NOT NULL,
            joined_at REAL NOT NULL,
            PRIMARY KEY(campaign_id,user_digest)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_campaign_state_end ON ad_campaigns(state,ends_at)")


class CampaignMixin:
    @staticmethod
    def _campaign_owner(actor_id, owner_id):
        if type(actor_id) is not int or type(owner_id) is not int or actor_id <= 0 or owner_id <= 0:
            raise ValueError("Invalid owner identity")
        if actor_id != owner_id:
            raise PermissionError("Owner authorization required")

    @staticmethod
    def _campaign_chat(chat_id):
        if type(chat_id) is not int or not -(2**63) <= chat_id < 0:
            raise ValueError("Invalid channel ID")

    @staticmethod
    def _campaign_id(campaign_id):
        if not isinstance(campaign_id, str) or not _CAMPAIGN.fullmatch(campaign_id):
            raise ValueError("Invalid campaign ID")

    @staticmethod
    def _invite_link(value):
        # Bot-created private invite links; no arbitrary URLs or URL parameters.
        if (not isinstance(value, str) or len(value) > 256
                or not re.fullmatch(r"https://t\.me/\+[A-Za-z0-9_-]{8,128}", value)):
            raise ValueError("Invalid Telegram invite link")

    @serialized
    def create_campaign(self, *, actor_id, owner_id, chat_id, mode, starts_at,
                        ends_at, target_joins=None, now=None):
        self._campaign_owner(actor_id, owner_id)
        self._campaign_chat(chat_id)
        if mode not in _MODES:
            raise ValueError("Invalid campaign mode")
        start = _timestamp(starts_at, label="start")
        end = _timestamp(ends_at, label="end")
        if end <= start:
            raise ValueError("Campaign end must follow start")
        if mode == "joins":
            if type(target_joins) is not int or not 1 <= target_joins <= 1_000_000:
                raise ValueError("Invalid confirmed join target")
        elif target_joins is not None:
            raise ValueError("Timed campaign cannot have a join target")
        now = _timestamp(time.time() if now is None else now)
        campaign_id = secrets.token_urlsafe(24)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                """INSERT INTO ad_campaigns(campaign_id,chat_id,mode,target_joins,
                   starts_at,ends_at,state,created_at)
                   VALUES(?,?,?,?,?,?,'draft',?)""",
                (campaign_id, chat_id, mode, target_joins, start, end, now),
            )
            self._db.execute(
                "INSERT INTO owner_audit(actor_id,action,target_chat_id,occurred_at) VALUES(?,?,?,?)",
                (actor_id, "campaign_create", chat_id, now),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return campaign_id

    @serialized
    def bind_campaign_invite(self, *, actor_id, owner_id, campaign_id,
                             invite_link, now=None):
        self._campaign_owner(actor_id, owner_id)
        self._campaign_id(campaign_id)
        self._invite_link(invite_link)
        now = _timestamp(time.time() if now is None else now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT chat_id,state,invite_link FROM ad_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown campaign")
            if row[1] != "draft" or row[2] is not None:
                raise ValueError("Invite link cannot be rebound")
            self._db.execute(
                "UPDATE ad_campaigns SET invite_link=? WHERE campaign_id=?",
                (invite_link, campaign_id),
            )
            self._db.execute(
                "INSERT INTO owner_audit(actor_id,action,target_chat_id,occurred_at) VALUES(?,?,?,?)",
                (actor_id, "campaign_bind_invite", row[0], now),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @serialized
    def change_campaign_state(self, *, actor_id, owner_id, campaign_id, action, now=None):
        self._campaign_owner(actor_id, owner_id)
        self._campaign_id(campaign_id)
        now = _timestamp(time.time() if now is None else now)
        transitions = {
            ("draft", "start"): "active",
            ("active", "pause"): "paused",
            ("paused", "resume"): "active",
            ("draft", "stop"): "stopped",
            ("active", "stop"): "stopped",
            ("paused", "stop"): "stopped",
        }
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT chat_id,state,starts_at,ends_at,invite_link FROM ad_campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown campaign")
            target = transitions.get((row[1], action))
            if target is None:
                raise ValueError("Illegal campaign transition")
            if action in {"start", "resume"} and (not row[4] or not row[2] <= now < row[3]):
                raise ValueError("Campaign not ready or outside schedule")
            self._db.execute(
                "UPDATE ad_campaigns SET state=? WHERE campaign_id=?",
                (target, campaign_id),
            )
            self._db.execute(
                "INSERT INTO owner_audit(actor_id,action,target_chat_id,occurred_at) VALUES(?,?,?,?)",
                (actor_id, "campaign_" + action, row[0], now),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return target

    @serialized
    def record_confirmed_join(self, *, campaign_id, user_digest, observed_invite,
                              joined_at=None):
        """Internal-only trusted adapter; never expose to client-facing API.

        A verified Telegram join must carry the campaign's exact invite link.
        This does not imply continued membership or a click impression.
        """
        self._campaign_id(campaign_id)
        if not isinstance(user_digest, str) or not _DIGEST.fullmatch(user_digest):
            raise ValueError("Expected keyed user digest")
        self._invite_link(observed_invite)
        joined_at = _timestamp(time.time() if joined_at is None else joined_at)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                """SELECT state,starts_at,ends_at,invite_link,mode,target_joins,confirmed_joins
                   FROM ad_campaigns WHERE campaign_id=?""",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown campaign")
            state, start, end, invite, mode, target, count = row
            if state != "active" or not start <= joined_at < end or invite != observed_invite:
                self._db.execute("COMMIT")
                return False
            cursor = self._db.execute(
                """INSERT OR IGNORE INTO ad_campaign_joins(campaign_id,user_digest,joined_at)
                   VALUES(?,?,?)""",
                (campaign_id, user_digest, joined_at),
            )
            if cursor.rowcount:
                count += 1
                next_state = "completed" if mode == "joins" and count >= target else state
                self._db.execute(
                    "UPDATE ad_campaigns SET confirmed_joins=?,state=? WHERE campaign_id=?",
                    (count, next_state, campaign_id),
                )
            self._db.execute("COMMIT")
            return cursor.rowcount == 1
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @serialized
    def record_attributed_join(self, *, chat_id, invite_link, user_digest, joined_at):
        """Resolve only the stored chat/link pair, then atomically deduplicate.

        Never trust a campaign ID from an incoming Telegram event. The outer
        store RLock keeps lookup and write serialized in this API worker.
        """
        self._campaign_chat(chat_id)
        self._invite_link(invite_link)
        row = self._db.execute(
            "SELECT campaign_id FROM ad_campaigns WHERE chat_id=? AND invite_link=?",
            (chat_id, invite_link),
        ).fetchone()
        if row is None:
            return False
        return self.record_confirmed_join(
            campaign_id=row[0], user_digest=user_digest,
            observed_invite=invite_link, joined_at=joined_at,
        )

    @serialized
    def expire_campaigns(self, *, now=None):
        now = _timestamp(time.time() if now is None else now)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            changed = self._db.execute(
                """UPDATE ad_campaigns SET state='completed'
                   WHERE state IN ('active','paused') AND ends_at<=?""",
                (now,),
            ).rowcount
            self._db.execute("COMMIT")
            return changed
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @serialized
    def campaign_snapshot(self, *, actor_id, owner_id, campaign_id):
        self._campaign_owner(actor_id, owner_id)
        self._campaign_id(campaign_id)
        row = self._db.execute(
            """SELECT campaign_id,chat_id,mode,target_joins,starts_at,ends_at,
               state,confirmed_joins,invite_link FROM ad_campaigns WHERE campaign_id=?""",
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise KeyError("Unknown campaign")
        keys = ("campaign_id","chat_id","mode","target_joins","starts_at","ends_at",
                "state","confirmed_joins","invite_link")
        return dict(zip(keys,row))
