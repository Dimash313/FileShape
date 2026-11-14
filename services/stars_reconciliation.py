"""Recover real Telegram Stars invoice payments from authoritative transaction history.

Telegram Bot API getStarTransactions includes incoming invoice payload, buyer
and charge ID. This backfills a successful_payment update lost while the bot
or API was offline without a bot-side copy of the API SQLite database.

Bounded scans cannot guarantee completeness beyond MAX_HISTORY_PAGES or after
Telegram stops exposing old transactions; report truncation for operators.
"""
import asyncio
import logging
import re
import time

from services.stars_bridge import (
    StarsBridgeUnavailable, confirm_stars_payment,
)

logger = logging.getLogger(__name__)

_HISTORY_PAGE_SIZE = 100
MAX_HISTORY_PAGES = 10
HISTORY_LOOKBACK_SECONDS = 30 * 86400
HISTORY_SCAN_SECONDS = 300
_PAYLOAD = re.compile(r"fileshape:([0-9a-f]{32})\Z")


def _incoming_invoice(transaction):
    """Return strictly matched fields from Telegram's own transaction object."""
    partner = getattr(transaction, "source", None)
    if (partner is None or getattr(partner, "type", None) != "user"
            or getattr(partner, "transaction_type", None) != "invoice_payment"
            or getattr(transaction, "receiver", None) is not None):
        return None
    buyer = getattr(getattr(partner, "user", None), "id", None)
    payload = getattr(partner, "invoice_payload", None)
    charge = getattr(transaction, "id", None)
    amount = getattr(transaction, "amount", None)
    nanostars = getattr(transaction, "nanostar_amount", None)
    date = getattr(transaction, "date", None)
    if (
        type(buyer) is not int or not 0 < buyer <= 2**63 - 1
        or not isinstance(payload, str)
        or _PAYLOAD.fullmatch(payload) is None
        or type(amount) is not int or amount <= 0
        or nanostars not in (None, 0)
        or type(date) is not int or date <= 0
        or not isinstance(charge, str)
        or not 1 <= len(charge) <= 256
        or not charge.isascii()
    ):
        return None
    return buyer, payload[len("fileshape:"):], amount, charge, date


async def reconcile_star_transactions(
    bot, *, now=None, lookback_seconds=HISTORY_LOOKBACK_SECONDS,
    max_pages=MAX_HISTORY_PAGES,
):
    """Page Telegram's real transaction ledger and idempotently fulfill receipts.

    An incomplete traversal or failed confirmation is surfaced in the result,
    never marked as success. Does not use user messages, stored untrusted
    payloads or local SQLite for payment proof.
    """
    if now is None:
        now = time.time()
    if not isinstance(now, (int, float)) or isinstance(now, bool) or now <= 0:
        raise ValueError("Invalid reconciliation time")
    if (type(lookback_seconds) is not int or not 60 <= lookback_seconds <= 365 * 86400
            or type(max_pages) is not int or not 1 <= max_pages <= 20):
        raise ValueError("Invalid reconciliation bounds")
    start = now - lookback_seconds
    scanned = matched = delivered = failed = 0
    complete = False
    # Iterate all pages even when data appears old: Telegram documents
    # chronological order, but we cannot assume sort direction.
    for page in range(max_pages):
        response = await asyncio.wait_for(
            bot.get_star_transactions(offset=page * _HISTORY_PAGE_SIZE,
                                      limit=_HISTORY_PAGE_SIZE, request_timeout=20),
            timeout=25,
        )
        transactions = getattr(response, "transactions", None)
        if not isinstance(transactions, (list, tuple)):
            raise StarsBridgeUnavailable("Invalid Telegram StarTransactions response")
        if len(transactions) > _HISTORY_PAGE_SIZE:
            raise StarsBridgeUnavailable("Unexpected Telegram transaction page size")
        scanned += len(transactions)
        for transaction in transactions:
            invoice = _incoming_invoice(transaction)
            if invoice is None:
                continue
            owner, order_id, amount, charge_id, paid_at = invoice
            if paid_at < start or paid_at > now + 120:
                continue
            matched += 1
            try:
                await confirm_stars_payment(owner, bot.token, order_id,
                                            amount, "XTR", charge_id)
            except StarsBridgeUnavailable:
                failed += 1
                # Retries are safe: API records each Telegram charge exactly once.
            else:
                delivered += 1
        if len(transactions) < _HISTORY_PAGE_SIZE:
            complete = True
            break
    return {
        "scanned": scanned, "matched": matched,
        "confirmed": delivered, "failed": failed,
        "complete": complete,
    }


async def star_reconciliation_loop(bot):
    """Run from bot startup; a transient API outage must never stop polling."""
    while True:
        try:
            result = await reconcile_star_transactions(bot)
            if not result["complete"] or result["failed"]:
                logger.error(
                    "Stars reconciliation incomplete: scanned=%d matching=%d failed=%d",
                    result["scanned"], result["matched"], result["failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stars reconciliation could not read Telegram transactions")
        await asyncio.sleep(HISTORY_SCAN_SECONDS)
