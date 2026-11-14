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
    StarsBridgeUnavailable, confirm_stars_payment, confirm_stars_refund,
    confirm_stars_paid_and_refunded,
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


def _outgoing_invoice_refund(transaction):
    """Extract an authoritative outgoing Telegram refund, never a user claim.

    Refunds reuse their original incoming charge ID. Ledger reconciliation
    additionally requires that the exact charge belongs to this buyer.
    """
    partner = getattr(transaction, "receiver", None)
    if (partner is None or getattr(partner, "type", None) != "user"
            or getattr(partner, "transaction_type", None) not in (None, "invoice_payment")
            or getattr(transaction, "source", None) is not None):
        return None
    buyer = getattr(getattr(partner, "user", None), "id", None)
    charge = getattr(transaction, "id", None)
    amount = getattr(transaction, "amount", None)
    date = getattr(transaction, "date", None)
    invoice_payload = getattr(partner, "invoice_payload", None)
    if (
        type(buyer) is not int or not 0 < buyer <= 2**63 - 1
        or type(amount) is not int or amount >= 0
        or type(date) is not int or date <= 0
        or not isinstance(charge, str) or not 1 <= len(charge) <= 256
        or not charge.isascii()
        or (invoice_payload is not None and (
            not isinstance(invoice_payload, str)
            or _PAYLOAD.fullmatch(invoice_payload) is None
        ))
    ):
        return None
    return buyer, charge, -amount, date


async def reconcile_star_transactions(
    bot, *, now=None, lookback_seconds=HISTORY_LOOKBACK_SECONDS,
    max_pages=MAX_HISTORY_PAGES, acknowledged_charges=None,
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
    if acknowledged_charges is not None and not isinstance(acknowledged_charges, set):
        raise ValueError("Invalid confirmation cache")
    start = now - lookback_seconds
    scanned = matched = delivered = failed = refunded = refund_failed = 0
    complete = False
    events = []
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
        events.extend(transactions)
        if len(transactions) < _HISTORY_PAGE_SIZE:
            complete = True
            break
    # First process Telegram-confirmed refunds, *then* payments. The Bot API
    # does not promise which direction pages are ordered. A refunded payment
    # must not receive a new grant if both transaction entries are present.
    invoices = {}
    for transaction in events:
        invoice = _incoming_invoice(transaction)
        if invoice is None:
            continue
        owner, order_id, amount, charge_id, paid_at = invoice
        if start <= paid_at <= now + 120:
            invoices.setdefault(charge_id, (owner, order_id, amount))

    refunded_charges = set()
    for transaction in events:
        refund = _outgoing_invoice_refund(transaction)
        if refund is None:
            continue
        owner, charge_id, refund_amount, refunded_at = refund
        if refunded_at < start or refunded_at > now + 120:
            continue
        refunded_charges.add(charge_id)
        if acknowledged_charges is not None and "refund:" + charge_id in acknowledged_charges:
            continue
        paid = invoices.get(charge_id)
        try:
            if paid is not None:
                buyer, order_id, paid_amount = paid
                if buyer != owner or paid_amount != refund_amount:
                    # A different buyer, amount or charge must never be
                    # treated as proof of a fully refunded FileShape order.
                    refund_failed += 1
                    continue
                await confirm_stars_paid_and_refunded(
                    owner, bot.token, order_id, paid_amount, "XTR", charge_id,
                )
            else:
                await confirm_stars_refund(owner, bot.token, charge_id)
        except StarsBridgeUnavailable:
            refund_failed += 1
        else:
            refunded += 1
            if acknowledged_charges is not None:
                acknowledged_charges.add("refund:" + charge_id)

    for transaction in events:
        invoice = _incoming_invoice(transaction)
        if invoice is None:
            continue
        owner, order_id, amount, charge_id, paid_at = invoice
        if paid_at < start or paid_at > now + 120:
            continue
        matched += 1
        # A truncated history may hide a refund on a later page. Never
        # create a fresh paid entitlement from incomplete evidence.
        # Refund assertions above remain safe to process independently.
        if not complete:
            failed += 1
            continue
        if charge_id in refunded_charges:
            continue
        if acknowledged_charges is not None and "paid:" + charge_id in acknowledged_charges:
            continue
        try:
            await confirm_stars_payment(owner, bot.token, order_id,
                                        amount, "XTR", charge_id)
        except StarsBridgeUnavailable:
            failed += 1
        else:
            delivered += 1
            if acknowledged_charges is not None:
                acknowledged_charges.add("paid:" + charge_id)

    return {
        "scanned": scanned, "matched": matched,
        "confirmed": delivered, "failed": failed,
        "refunded": refunded, "refund_failed": refund_failed,
        "complete": complete,
    }


async def star_reconciliation_loop(bot):
    """Run from bot startup; a transient API outage must never stop polling."""
    # In-memory optimization only: authoritative idempotency is persisted in
    # the API. Startup replays from Telegram's ledger after every restart.
    acknowledged_charges = set()
    while True:
        try:
            result = await reconcile_star_transactions(
                bot, acknowledged_charges=acknowledged_charges,
            )
            if len(acknowledged_charges) > 2000:
                acknowledged_charges.clear()
            if not result["complete"] or result["failed"] or result["refund_failed"]:
                logger.error(
                    "Stars reconciliation incomplete: scanned=%d matching=%d paid_failed=%d refund_failed=%d",
                    result["scanned"], result["matched"], result["failed"], result["refund_failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stars reconciliation could not read Telegram transactions")
        await asyncio.sleep(HISTORY_SCAN_SECONDS)
