"""Pure access-policy decisions. Not yet wired to processing endpoints.

Membership observations must come from a trusted server-side Telegram API call.
Never trust client-provided status or treat API failures as confirmed membership.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class AccessDecision(str, Enum):
    ALLOWED = "allowed"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"


@dataclass(frozen=True)
class RequiredChannel:
    chat_id: int
    starts_at: datetime
    ends_at: datetime | None = None
    enabled: bool = True

    def __post_init__(self):
        if type(self.chat_id) is not int or self.chat_id == 0:
            raise ValueError("channel ID must be a nonzero integer")
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("starts_at must be timezone-aware")
        if self.ends_at is not None:
            if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
                raise ValueError("ends_at must be timezone-aware")
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must follow starts_at")

    def active_at(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.enabled and self.starts_at <= now and (
            self.ends_at is None or now < self.ends_at
        )


def membership_confirmed(status: str | None, *, is_member: bool | None = None) -> bool:
    """Telegram ChatMember statuses: restricted is valid only when is_member=True."""
    if status in {"creator", "administrator", "member"}:
        return True
    return status == "restricted" and is_member is True


def decide_access(
    *,
    premium_until: datetime | None,
    channels: tuple[RequiredChannel, ...],
    observations: dict[int, tuple[str | None, bool | None] | None],
    now: datetime | None = None,
) -> AccessDecision:
    """Decide from trusted observations; None means a failed/unavailable API check.

    Caller must authenticate user and fetch observations server-side. The decision
    alone is not authorization; every processing entry point must enforce it.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if premium_until is not None:
        if premium_until.tzinfo is None or premium_until.utcoffset() is None:
            raise ValueError("premium_until must be timezone-aware")
        if now < premium_until:
            return AccessDecision.ALLOWED
    active = [channel for channel in channels if channel.active_at(now)]
    if len({channel.chat_id for channel in active}) != len(active):
        raise ValueError("duplicate active channel ID")
    if not active:
        return AccessDecision.ALLOWED
    missing = False
    unavailable = False
    for channel in active:
        observation = observations.get(channel.chat_id)
        if observation is None:
            unavailable = True
        elif not membership_confirmed(*observation[:1], is_member=observation[1]):
            missing = True
    if missing:
        return AccessDecision.SUBSCRIPTION_REQUIRED
    if unavailable:
        return AccessDecision.VERIFICATION_UNAVAILABLE
    return AccessDecision.ALLOWED
