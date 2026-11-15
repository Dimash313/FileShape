# API & security — handoff

Updated: 2026-11-15 UTC; verify live GitHub PR SHA/Actions and architecture dependencies on each return.
Track: `api-security`.
Current issue: [#175](https://github.com/Dimash313/FileShape/issues/175), no-network tracked credential preflight.
Branch: `api-security/175-tracked-secret-preflight`.
PR: [#176](https://github.com/Dimash313/FileShape/pull/176) (Draft), targets `docs/independent-development-tracks` / unmerged [#112](https://github.com/Dimash313/FileShape/pull/112).

## Current focused change

- `tools/secret_scan.py`: standard-library-only scanner on `git ls-files --cached -z`, limited to 20k paths and 2 MiB per scanned file or binary prefix. High-confidence Telegram, GitHub, AWS, PEM private key, OpenAI, Stripe and Slack token patterns plus private credential filenames. Never prints matched bytes. Uses `O_NOFOLLOW` and `fstat()` pinned inode verification to reject a symlink replacement between `lstat()` and `open()`; scans the first 2 MiB of oversized media without loading entire binaries, fails closed on oversized text and read errors.
- `tests/test_secret_scan.py`: synthetic tokens composed dynamically, tracked vs untracked, private and example env files, invalid binary encoding, oversize text, safe path labels, symlink refusal, **lstat-to-open symlink substitution**, oversized binary-prefix detection, and missing Git repo.
- `.github/workflows/tests.yml`: new enforced `Reject accidentally committed credentials` step after Python 3.12 setup and before FFmpeg/dependency install. Existing full Python tests, Docker and Mini App are unchanged.
- No new packages, secrets, network calls, user media, music, imagery, payments or third-party services. Scanner is **not** Git-history auditing, revocation, nor a GitHub native secret-scanning substitute. Regex positives can require manual review.

**Conflict coordination:** existing [Draft PR #102](https://github.com/Dimash313/FileShape/pull/102) also updates `.github/workflows/tests.yml` with concurrency and pip download caching. Integrator must review/merge #102 first, then rebase/reconcile this scanner workflow change without discarding either improvement. This branch remains stacked on unmerged #112; main is not assumed to contain the architecture.

## CI and other API/security PRs

GitHub Actions issue [#101](https://github.com/Dimash313/FileShape/issues/101) is closed after owner's public repository switch; hosted runners and full CI have resumed. The initial PR #176 head `24ec2089e935304086076d51074504f3828b55ce` passed actual Python tests, Mini App tests/build and Docker plus new preflight ([Actions run #43731842965](https://github.com/Dimash313/FileShape/actions/runs/43731842965)). A later hardening run [#43733775398](https://github.com/Dimash313/FileShape/actions/runs/43733775398) for head `c29973d4f34b102ef08943ffa39dd5e095097e3e` **failed one test of 631**: synthetic oversized-media input appended alphanumeric filler directly to a token (no delimiter). The scanner correctly did not match the overlong string. Fixed the fixture with a newline delimiter and added a negative regression for no delimiter in commit `6c7df9d2770f493a7b4e3ccd38843ac52eb0526b`. **Current exact-head CI is pending**; do not treat that earlier red run as green. Require latest checked-out exact PR-head Python tests, Mini App tests/typecheck/build, Docker build and independent review, then owner-approved integration in correct ancestry order; no production-ready claim.

Other unmerged Drafts: #124 upload framing, #135 ZIP extraction HTTP design-only, #142 pinned published file identity, #151 privacy-safe request traces, #156 bounded queue admission, #164 bounded worker stdout, #170 child environment secret isolation stacked on #164. These had prior exact-head green CI; inspect live PRs to confirm no HEAD drift. Handoff STATUS edits on other branches must be reconciled with live issues rather than blindly overwritten.

## Next

1. Verify exact-head Draft PR #176 scanner + full CI, fix any failures, and obtain independent review. Do not merge based on fast green checks alone.
2. Coordinate workflow overlap with #102 and unmerged docs #112 via integration comment.
3. Ensure public-repository history and branches are separately audited for previously exposed keys. Rotate/revoke any *actual* credential found; the new scanner cannot retroactively erase exposure.
