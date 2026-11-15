# API & security — handoff

Updated: 2026-11-15 UTC; verify live GitHub PR SHA/Actions and architecture dependencies on each return.
Track: `api-security`.
Current issue: [#175](https://github.com/Dimash313/FileShape/issues/175), no-network tracked credential preflight.
Branch: `api-security/175-tracked-secret-preflight`.
PR: pending at time of this status edit; targets `docs/independent-development-tracks` / unmerged [#112](https://github.com/Dimash313/FileShape/pull/112).

## Current focused change

- `tools/secret_scan.py`: standard-library-only scanner on `git ls-files --cached -z`, limited to 20k paths and 2 MiB per individual nonbinary file. High-confidence Telegram, GitHub, AWS, PEM private key, OpenAI, Stripe and Slack token patterns plus tracked private credential filenames; no token bytes or excerpts are ever logged. Captures unusual binary encodings too, rejects tracked symlinks, large text and read errors.
- `tests/test_secret_scan.py`: synthetic tokens composed dynamically, tracked vs untracked, private and example env files, invalid binary encoding, oversize text, safe path labels, symlink refusal and missing Git repo.
- `.github/workflows/tests.yml`: new enforced `Reject accidentally committed credentials` step after Python 3.12 setup and before FFmpeg/dependency install. Existing full Python tests, Docker and Mini App are unchanged.
- No new packages, secrets, network calls, user media, music, imagery, payments or third-party services. Scanner is **not** Git-history auditing, revocation, nor a GitHub native secret-scanning substitute. Regex positives can require manual review.

**Conflict coordination:** existing [Draft PR #102](https://github.com/Dimash313/FileShape/pull/102) also updates `.github/workflows/tests.yml` with concurrency and pip download caching. Integrator must review/merge #102 first, then rebase/reconcile this scanner workflow change without discarding either improvement. This branch remains stacked on unmerged #112; main is not assumed to contain the architecture.

## CI and other API/security PRs

GitHub Actions issue [#101](https://github.com/Dimash313/FileShape/issues/101) is closed after owner's public repository switch; hosted runners and full CI have resumed. **No exact-head CI was run/observed for #175 at status-writing time**. Require checked-out exact PR-head Python tests, Mini App tests/typecheck/build, Docker build, independent review, then owner-approved integration in correct ancestry order; no CI-green or production-ready claim before results.

Other unmerged Drafts: #124 upload framing, #135 ZIP extraction HTTP design-only, #142 pinned published file identity, #151 privacy-safe request traces, #156 bounded queue admission, #164 bounded worker stdout, #170 child environment secret isolation stacked on #164. These had prior exact-head green CI; inspect live PRs to confirm no HEAD drift. Handoff STATUS edits on other branches must be reconciled with live issues rather than blindly overwritten.

## Next

1. Create Draft PR for Issue #175; inspect exact-head scan + full CI and fix any false positives / test failures. Do not merge based only on fast green checks.
2. Coordinate workflow overlap with #102 and unmerged docs #112 via integration comment.
3. Ensure public-repository history and branches are separately audited for previously exposed keys. Rotate/revoke any *actual* credential found; the new scanner cannot retroactively erase exposure.
