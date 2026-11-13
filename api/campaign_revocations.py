"""Best-effort Telegram revocation dispatcher backed by a durable retry queue.

Never mark a private link revoked unless Telegram acknowledged the request.
Only the API owner worker reads/writes the SQLite revocation ledger. Pending
revocations survive restarts; individual failures do not block other links.
"""
import asyncio
import logging
import time

from aiogram import Bot

from config import get_settings
from services.campaign_telegram import revoke_campaign_invite


logger = logging.getLogger(__name__)
_dispatch_lock = asyncio.Lock()


async def dispatch_campaign_revocations(store, *, now=None, limit=10, bot=None):
    """Revoke due links; return number acknowledged by Telegram.

    A single process-local lock prevents the maintenance worker and join/owner
    endpoints from simultaneously revoking one invite. The application uses
    one API worker, as required by its durable SQLite owner.
    """
    async with _dispatch_lock:
        now = time.time() if now is None else now
        pending = store.pending_campaign_revocations(now=now, limit=limit)
        if not pending:
            return 0

        owns_bot = bot is None
        if owns_bot:
            bot = Bot(token=get_settings().bot_token)
        acknowledged = 0
        try:
            for item in pending:
                try:
                    await asyncio.wait_for(
                        revoke_campaign_invite(
                            bot, chat_id=item["chat_id"],
                            invite_link=item["invite_link"],
                        ),
                        timeout=10,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Do not log Telegram's exception, URL, token or user IDs.
                    store.record_campaign_revocation_failure(
                        campaign_id=item["campaign_id"],
                        chat_id=item["chat_id"],
                        invite_link=item["invite_link"],
                        now=now,
                    )
                    logger.warning(
                        "Campaign invite revocation failed; queued for retry"
                    )
                else:
                    if store.record_campaign_revoked(
                        campaign_id=item["campaign_id"],
                        chat_id=item["chat_id"],
                        invite_link=item["invite_link"],
                        now=now,
                    ):
                        acknowledged += 1
        finally:
            if owns_bot:
                await bot.session.close()
        return acknowledged
