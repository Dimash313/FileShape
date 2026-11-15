# API & security — handoff

Updated: 2026-11-15 UTC.
Track: `api-security`.
Current Issue: [#120](https://github.com/Dimash313/FileShape/issues/120).
Active PR: [#124](https://github.com/Dimash313/FileShape/pull/124) (**Draft**; base `docs/independent-development-tracks`, itself unmerged PR #112).
Branch: `api-security/120-upload-framing`.
Code/test commit: `5e7dce4a1bd46b16b1c351cffdda77d22f010530` (the STATUS update itself advances branch HEAD; inspect PR #124 for the exact latest commit).

## P0 — CI blocker #101 (unresolved)

GitHub Actions hosted runner allocation remains broken before any test execution. Run [43709270266](https://github.com/Dimash313/FileShape/actions/runs/43709270266) for Draft PR #102 and later runs [43720058288](https://github.com/Dimash313/FileShape/actions/runs/43720058288) and [43720144330](https://github.com/Dimash313/FileShape/actions/runs/43720144330) show **both jobs failed with `runner_id=0` and zero steps**. The diagnostic evidence was recorded as a comment on [Issue #101](https://github.com/Dimash313/FileShape/issues/101). The exact check-run annotation/account billing policy is not visible through the connector. **Root cause not confirmed, not resolved; no PR may merge on these results.**

Owner action: inspect the workflow failure banner/annotation in GitHub UI, the account Actions usage/budgets, and repository Settings → Actions → General. Do not enable paid overages or relax spending protection without explicit owner consent. If all account settings are normal, contact GitHub Support with the failing run IDs and exact banner text.

## Work performed in this branch

- `api/ingress.py`: reject duplicate `Content-Length` fields, incompatible `Content-Length` and `Transfer-Encoding`, and noncanonical lengths at the HTTP upload guard; preserve cap on actual streamed bytes and 413 behavior.
- `tests/test_ingress.py`: adversarial framing regressions, mixed-case header names, valid transfer-only chunked upload and overlimit rejection.
- No shared `api/server.py`, domain formats, database, payments or third-party services changed.

**Verified:** GitHub commits created; code and regressions inspected, but **tests NOT EXECUTED on the exact PR head**, Docker build NOT EXECUTED and Mini App checks NOT EXECUTED. A Draft PR is not a completed/released milestone.

## Dependency and next actions

1. Resolve #101 with the owner; require a real runner, executed Python/Mini App/Docker jobs, exact-head success and review before merging #124.
2. Integrate parent [PR #112](https://github.com/Dimash313/FileShape/pull/112) and its architecture stack in dependency order; never merge this stacked PR independently into main.
3. Audit PR #87 vs #107 capability discovery duplication, #108 PDF merge and #109 ZIP create route ownership, and plan a secure ZIP extract result contract with images/archives.
4. Preserve Telegram-signed auth, tenant isolation, file lifecycle, atomic quota ledger and checked resource limits for every public ingress.
