"""Owner-authorized Stars refund primitive; no public command or auto-refunds.

Only when Telegram confirms refundStarPayment can API accounting be reversed.
A successful Telegram refund followed by API outage needs explicit reconciliation.
"""
import os

from services.stars_bridge import StarsBridgeUnavailable, confirm_stars_refund


class StarsRefundReconciliationRequired(Exception):
    """Telegram refund succeeded, but server-side reversal is still pending."""


def _authorized_owner(actor_id: int) -> bool:
    if type(actor_id) is not int or not 0 < actor_id <= 2**63 - 1:
        return False
    try:
        owner_id = int(os.environ.get("FILESHAPE_OWNER_ID", "").strip())
    except ValueError:
        return False
    return owner_id > 0 and actor_id == owner_id


async def refund_stars_verified(bot, *, actor_id: int, buyer_id: int,
                                telegram_charge_id: str) -> dict:
    """Use only from an explicitly authorized owner workflow.

    This is deliberately not exposed as a bot command in 4.24 yet.
    """
    if not _authorized_owner(actor_id):
        raise PermissionError("Only the bot owner may refund Stars")
    if (type(buyer_id) is not int or not 0 < buyer_id <= 2**63 - 1
            or not isinstance(telegram_charge_id, str)
            or not 1 <= len(telegram_charge_id) <= 256):
        raise ValueError("Invalid refund recipient or charge")
    # Never reverse a payment simply because the owner typed a charge ID.
    # The Telegram Bot API must explicitly confirm refund success first.
    acknowledged = await bot.refund_star_payment(
        user_id=buyer_id, telegram_payment_charge_id=telegram_charge_id,
    )
    if acknowledged is not True:
        raise RuntimeError("Telegram did not confirm Stars refund")
    try:
        return await confirm_stars_refund(
            buyer_id, bot.token, telegram_charge_id,
        )
    except StarsBridgeUnavailable:
        raise StarsRefundReconciliationRequired(
            "Telegram refund succeeded; the API reversal must be reconciled"
        ) from None
