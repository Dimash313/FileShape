# Images & archives — handoff

Updated: 2026-11-15 UTC.
Track: `images-archives`.
Branch: `fix/zip-extraction-failure-cleanup-g1`.
Code + test snapshot head before STATUS update: `602f07da40d062ab6e2d60dd647293b4779987d8`. For the **final** exact head SHA and checks, inspect PR #128 live (this handoff update is itself another commit).

## Current work
- Issue: [#121 — ZIP extraction staged publication, no-clobber and cleanup](https://github.com/Dimash313/FileShape/issues/121), claimed.
- Active PR: [#128](https://github.com/Dimash313/FileShape/pull/128), **Draft**, base `docs/independent-development-tracks`.
- Dependency chain: [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) (Issue [#110](https://github.com/Dimash313/FileShape/issues/110)) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture parents. None is merged as of this snapshot. Do **not** merge #128 ahead of its parents.

## Proposed implementation in PR #128 (not in main)
- `services/archive_tools.py`: preflight + validation on the same ZIP object subsequently extracted; private in-output-directory staging; bounded streaming with existing byte/bomb/count/path/encryption checks; hard-link-based non-overwriting publication and rollback on partial publication failure. Preserve 01_/02_ filenames, order and return interface.
- `tests/test_archive_extraction_cleanup.py`: nine tests for good output, bad second-file CRC, collision with existing file and symlink, failure on second publish, actual-byte overrun, archive replacement between inspect/open, high ratio + count limits, and symlink destination folder.
- No new HTTP route, format, shared API contract, payment, billing, database, user-facing content, imagery, music or provider integration.

## Verification (precise)
- Locally executed on a manually mirrored inspector/extractor + matching focused scenarios (not a full repo checkout): `python -m unittest -v tests.test_archive_extraction_cleanup` — **9/9 passed**, Python 3.13, Linux.
- This does **not** establish an exact-head PR test pass. Full repo Python suite, Mini App tests/typecheck/build, Docker, production-like Telegram ZIP integration, cross-format and exact-head GitHub Actions: **NOT EXECUTED / NOT VERIFIED** for this PR.
- GitHub Actions [runner allocation blocker #101](https://github.com/Dimash313/FileShape/issues/101) remains an integration gate. Do not treat zero-step checks as green.

## Risks and integration checks
- Output publication uses same-volume hardlinks (no second 50 MiB copy); verify support on the deployment filesystem. Publication is sequential, not simultaneous visibility of an entire multi-file batch; on error the extractor attempts to remove its own published links. Filesystem permissions or a failed unlink can still prevent cleanup; the owner workspace remains the final cleanup boundary.
- Tests must run against the **exact PR head** and against the full existing ZIP bot + HTTP suite before merge.
- ZIP HTTP **extraction** remains unimplemented; coordinate owner-scoped multi-file delivery with `api-security` before any shared API change.

Next unblocked Issue: **NONE currently assigned** (review #128 and verify #110 first; further image safety tests can be scoped to a new non-overlapping Issue).
