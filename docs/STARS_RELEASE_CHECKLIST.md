# FileShape 4.24 — Telegram Stars release gate

**Status: implementation in draft PR #69. No production Stars sales or live transaction tests have been verified.** Keep `FILESHAPE_STARS_CHECKOUT_ENABLED=false` in the production bot and API until the entire gate has independent evidence.

## Preconditions

- Use only the [official Telegram Stars digital-goods API](https://core.telegram.org/bots/payments-stars). No card processor or third-party payment provider for XTR.
- Test through Telegram's [dedicated test environment](https://core.telegram.org/bots/features#testing-your-bot) with a separate test bot. Never confuse test charges with live revenue.
- Configure a **real, responsive** payment-support Telegram username (`FILESHAPE_SUPPORT_USERNAME`) and show support/terms to buyers. Verify operator authorization and applicable legal requirements before accepting payments.
- Run one API worker with private service-owned SQLite state, persistent volume, and matching bot/API signing token. Do not expose `/internal/v1/stars/*` on a public reverse proxy.
- Confirm deployed bot actually has a working `FILESHAPE_ACCESS_GATE_URL` or `FILESHAPE_STARS_GATE_URL`. Production checkout must remain off by default.

## Required reproducible test cases

| Check | Expected, observable result |
| --- | --- |
| Disabled flag, missing support, bad gate URL | No invoice; pre-checkout denied; no grant |
| Invoice for each of the three server products | Owner-bound order, one correct XTR price, payload matching the order |
| Buyer terms and confirmation | /terms explains prices, limits, non-recurring Pro, refund contact and support; selecting a tariff only shows terms; only a current-version explicit agreement can produce an invoice; stale consent does not |
| Expired/wrong-user/wrong-price quote | Pre-checkout denied within Telegram's 10-second limit |
| Valid successful_payment event | Durable unique Telegram charge ID; exactly one entitlement/pack grant |
| Duplicate update; bot retry; API timeout after writing | Replayed event causes **no** second grant |
| Concurrent paid receipt delivery across API connections | Single ledger transition, no double value |
| Bot or API restart between receipt and fulfillment | API reconciles a verified receipt; no loss or duplication |
| API offline for weeks after successful pre-checkout | Approved quote is retained, delayed successful payment can still be recorded and fulfilled; legacy invoices are also retained |
| Bot offline during successful_payment | Bot's getStarTransactions backfill identifies correct buyer/charge/payload; confirms exactly once |
| Partial/invalid/unrelated outgoing Star transaction | Never treated as proof of a full refund; ambiguous input never grants |
| Full refund immediately after payment | Exactly one refund; packs revoked or recorded as debt; Pro remaining time corrected |
| Payment and refund both missed while bot offline | One atomic paid-plus-refunded record; **zero temporary paid value** |
| Refund succeeds in Telegram but API goes offline | Owner alert; eventually reconciled from Telegram record or manually investigated |
| More than 1000 transactions or incomplete Telegram history | Warning/owner notification, **no fresh grant from incomplete history**; must be investigated |
| Bad HMAC, expired nonce, altered amount/owner/charge | Rejected without changing ledgers |
| After a refund, pending worker fails and its reserved pack operation returns | Debt decreases; credit never becomes spendable prematurely |
| Files, job IDs, user privacy | Billing database stores only owner, order, charge, timestamps and amounts; no user files |
| Public bot support entry point | `/paysupport` reaches a real operator and supports refund investigation |

## Test-session evidence record (operator, not automated)

Run this on a **separate Telegram test bot and test API/SQLite volume**.
Do not use real customers or copy production bot tokens into a test repository.

1. Set the test bot and test API to the same internal signing token and
   reachable private Stars endpoint; configure a real support username.
   Keep the production flag `FILESHAPE_STARS_CHECKOUT_ENABLED=false`.
2. On the isolated test environment only, enable the Stars checkout flag on
   **both** services, then send `/start` and open the Stars purchase menu.
3. For each product, save a redacted screenshot of the invoice's **XTR price**,
   the Telegram payment confirmation, and the corresponding server-side
   order state (`fulfilled`). Do not capture tokens, Telegram charge IDs,
   customer IDs or raw private database dumps in public CI artifacts.
4. Re-deliver the same trusted payment event, restart bot and API, and
   confirm the balance/expiry is unchanged after reconciliation.
5. Stop the API, complete a **test** invoice, restore the API and wait for
   the history scanner; confirm one grant and no unacknowledged receipt.
6. Use the official test-environment refund mechanism, including a refund
   while the API is unreachable. Confirm a `refunded` order and correct
   balance/debt or Pro expiry, with no subsequent re-grant.
7. Intentionally break the internal endpoint and truncate the transaction
   scan; verify owner-only alerts and that no new grant is made from
   incomplete history. Restore the endpoint and repeat a complete scan.
8. Disable checkout on both test services and verify new invoices are
   refused. Record the test date, environment, redacted evidence location,
   Git commit SHA, expected vs observed results, and operator sign-off.

If the official Telegram test environment does not support a refund scenario,
record it as **not tested** and keep the production release gate closed.
A green GitHub Actions run does not prove any of these Telegram interactions.

## Production readiness decision

1. Green final-head GitHub Actions: full Python tests, Mini App typecheck/build, Docker image build.
2. Confirm green **merged main** Actions only *after* all payment gates are satisfied.
3. Review deployment readiness, observability (especially transaction-history truncation), customer support and refund procedure with the owner.
4. Record evidence for successful Telegram **test** payments and refunds. Synthetic mocks and GitHub CI do **not** substitute.
5. Enable checkout **only** through an explicit, separately authorized deployment decision; then monitor payments and owner alerts. Revert to disabled if reconciliation is incomplete.

**Known limitation:** `getStarTransactions` returns bounded pages. Reconciliation scans a 30-day window of at most 1000 transactions per pass and does not guarantee recovery for older charges or bots with extremely large histories. A truncated scan is an operator-visible blocker, not a green billing status.
