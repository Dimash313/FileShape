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
| Expired/wrong-user/wrong-price quote | Pre-checkout denied within Telegram's 10-second limit |
| Valid successful_payment event | Durable unique Telegram charge ID; exactly one entitlement/pack grant |
| Duplicate update; bot retry; API timeout after writing | Replayed event causes **no** second grant |
| Concurrent paid receipt delivery across API connections | Single ledger transition, no double value |
| Bot or API restart between receipt and fulfillment | API reconciles a verified receipt; no loss or duplication |
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

## Production readiness decision

1. Green final-head GitHub Actions: full Python tests, Mini App typecheck/build, Docker image build.
2. Confirm green **merged main** Actions only *after* all payment gates are satisfied.
3. Review deployment readiness, observability (especially transaction-history truncation), customer support and refund procedure with the owner.
4. Record evidence for successful Telegram **test** payments and refunds. Synthetic mocks and GitHub CI do **not** substitute.
5. Enable checkout **only** through an explicit, separately authorized deployment decision; then monitor payments and owner alerts. Revert to disabled if reconciliation is incomplete.

**Known limitation:** `getStarTransactions` returns bounded pages. Reconciliation scans a 30-day window of at most 1000 transactions per pass and does not guarantee recovery for older charges or bots with extremely large histories. A truncated scan is an operator-visible blocker, not a green billing status.
