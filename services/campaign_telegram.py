"""Telegram-side helpers for attributable campaign invitations and join events.

These helpers never claim that an invite click or membership check is a join.
A future authenticated bot-to-API bridge must transport the verified events.
"""
import hashlib
import hmac
import re
from dataclasses import dataclass

from aiogram.types import ChatMemberUpdated


_PRIVATE_INVITE = re.compile(r"https://t\.me/\+[A-Za-z0-9_-]{8,128}\Z")
_JOINED = {"member", "administrator", "creator"}


@dataclass(frozen=True)
class ConfirmedJoin:
    chat_id: int
    member_id: int
    invite_link: str
    event_time: int


def keyed_member_digest(token: str, member_id: int) -> str:
    """Pseudonymize Telegram member IDs; never use unsalted SHA256."""
    if not isinstance(token, str) or not token:
        raise ValueError("Missing signing secret")
    if type(member_id) is not int or not 0 < member_id <= 2**63 - 1:
        raise ValueError("Invalid member")
    key = hmac.new(token.encode(), b"fileshape-campaign-user-v1", hashlib.sha256).digest()
    return hmac.new(key, str(member_id).encode("ascii"), hashlib.sha256).hexdigest()


def _is_member(member) -> bool:
    status = str(getattr(member, "status", ""))
    if status in _JOINED:
        return True
    return status == "restricted" and getattr(member, "is_member", None) is True


def parse_confirmed_join(event: ChatMemberUpdated) -> ConfirmedJoin | None:
    """Only attribute a *new* membership with the exact invite from the update.

    Ignore joins without a link (including administrator additions), bots,
    departures, promotions and membership refreshes. Telegram sometimes omits
    invite_link for joins; those cannot be attributed and are not counted.
    """
    if not isinstance(event, ChatMemberUpdated):
        raise TypeError("Expected Telegram chat_member update")
    if _is_member(event.old_chat_member) or not _is_member(event.new_chat_member):
        return None
    member = event.new_chat_member.user
    if member.is_bot or type(member.id) is not int or member.id <= 0:
        return None
    chat_id = event.chat.id
    if type(chat_id) is not int or chat_id >= 0:
        return None
    link = getattr(event.invite_link, "invite_link", None)
    if not isinstance(link, str) or not _PRIVATE_INVITE.fullmatch(link):
        return None
    timestamp = int(event.date.timestamp())
    if timestamp <= 0:
        return None
    return ConfirmedJoin(chat_id, member.id, link, timestamp)


async def create_campaign_invite(bot, *, chat_id: int, campaign_id: str) -> str:
    """Create a unique bot-owned link; caller must be authenticated owner.

    Telegram bot needs can_invite_users in the partner's channel. Do not
    fabricate an invite if Telegram rejects the request.
    """
    if type(chat_id) is not int or chat_id >= 0:
        raise ValueError("Invalid channel")
    if not isinstance(campaign_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", campaign_id):
        raise ValueError("Invalid campaign")
    invite = await bot.create_chat_invite_link(
        chat_id=chat_id, name=f"FileShape {campaign_id[:24]}",
        creates_join_request=False,
    )
    link = invite.invite_link
    if not _PRIVATE_INVITE.fullmatch(link):
        raise ValueError("Telegram returned unsupported invite link")
    return link


async def revoke_campaign_invite(bot, *, chat_id: int, invite_link: str) -> None:
    """Stop future uses of a bot-owned link; never infer that members left."""
    if type(chat_id) is not int or chat_id >= 0:
        raise ValueError("Invalid channel")
    if not isinstance(invite_link, str) or not _PRIVATE_INVITE.fullmatch(invite_link):
        raise ValueError("Invalid invite")
    await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=invite_link)
