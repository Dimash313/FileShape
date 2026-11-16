# Track: API, security & infrastructure — roadmap

**Scope:** shared processing HTTP contracts, auth/session boundaries, quota/ledger, worker scheduling, resource admission, storage lifecycle, database migrations, CI, deployment and security integration.

1. **P0: unblock CI issue #101**; verify why jobs fail before runner allocation, review CI PR #102, confirm billing/runner settings with repository owner if needed. No merges while checks are absent.
2. Inventory stacked architecture PRs #93–#111, shared files, API capability discovery #107, PDF merge #108, ZIP create #109 and dependency order; identify conflicting/duplicated implementations (including earlier capability PR #87).
3. Design and review secure ZIP extraction HTTP result delivery with images/archives. Owner-bound, bounded output counts/bytes, TTL and cleanup; avoid exposing anonymous URLs.
4. Maintain versioned capability discovery derived from **implemented** HTTP routes only; no promises of unbuilt features.
5. Design standalone FileShape website/mobile identity adapters without universal IhsanSoft ID; no implementation or paid service without approval.
6. Continuous hardening: rate/quotas, SQLite concurrency, idempotency, worker timeouts, resource caps, privacy, audits and rollback.

Each task requires a dedicated Issue, risk/acceptance criteria, review, CI and STATUS update.
