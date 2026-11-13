"""Trusted Telegram membership observations for the access policy.

The caller must supply a server-authenticated user ID and configured channels.
This module does not install an admission gate on any processing endpoint.
"""
import asyncio
import logging
from datetime import datetime, timezone

from api.access_policy import AccessDecision, RequiredChannel, decide_access

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 5.0


async def verify_memberships(bot, *, user_id: int,
                             channels: tuple[RequiredChannel, ...],
                             premium_until: datetime | None = None,
                             now: datetime | None = None) -> AccessDecision:
    """Fail closed for Telegram errors, while allowing active Premium bypass.

    Uses only trusted bot.get_chat_member responses. Does not accept status
    assertions from clients, and checks each active channel independently.
    """
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise ValueError("Invalid authenticated user")
    if now is None:
        now = datetime.now(timezone.utc)
    # Validate time/channel configuration before any network activity.
    initial = decide_access(
        premium_until=premium_until, channels=channels, observations={}, now=now,
    )
    if initial is AccessDecision.ALLOWED:
        return initial

    active = tuple(channel for channel in channels if channel.active_at(now))
    observations = {}
    for channel in active:
        try:
            member = await asyncio.wait_for(
                bot.get_chat_member(chat_id=channel.chat_id, user_id=user_id),
                timeout=CHECK_TIMEOUT_SECONDS,
            )
            status = getattr(member, "status", None)
            is_member = getattr(member, "is_member", None)
            if not isinstance(status, str):
                observations[channel.chat_id] = None
            else:
                observations[channel.chat_id] = (
                    status, is_member if type(is_member) is bool else None,
                )
        except (Exception):
            logger.warning("Telegram membership verification unavailable for configured channel")
            observations[channel.chat_id] = None
    return decide_access(
        premium_until=premium_until, channels=channels,
        observations=observations, now=now,
    )
