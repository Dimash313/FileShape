# PDF & documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.
Current Issue: [#157 — count nested DOCX tables against resource limits](https://github.com/Dimash313/FileShape/issues/157).
Active PR: [#160](https://github.com/Dimash313/FileShape/pull/160) **DRAFT**. Branch `pdf-documents/157-nested-table-quotas`; base `pdf-documents/150-vertical-merge-guard` ([PR #154](https://github.com/Dimash313/FileShape/pull/154)).
Code+test commit before status edit: `6588439621fd0bbac88fcbf26f48cd36a25b8ba3`. This status commit advances the branch head; always query GitHub for the final exact head SHA.

## Implemented only in unmerged Draft PRs
- [#125](https://github.com/Dimash313/FileShape/pull/125) / Issue [#119](https://github.com/Dimash313/FileShape/issues/119): reject unsafe/ambiguous DOCX ZIP parts, duplicate names and symlinks.
- [#130](https://github.com/Dimash313/FileShape/pull/130) / Issue [#129](https://github.com/Dimash313/FileShape/issues/129): normalize corrupt OOXML parser exceptions without revealing internal paths.
- [#146](https://github.com/Dimash313/FileShape/pull/146) / Issue [#140](https://github.com/Dimash313/FileShape/issues/140): bound 5,000 top-level table rows / 20,000 expanded grid cells / 64 grid cells per row and incrementally check text length.
- [#154](https://github.com/Dimash313/FileShape/pull/154) / Issue [#150](https://github.com/Dimash313/FileShape/issues/150): bound vertical `w:vMerge` chains and check predecessor spans before recursive `row.cells` expansion.
- **[#160](https://github.com/Dimash313/FileShape/pull/160) / Issue [#157](https://github.com/Dimash313/FileShape/issues/157)**: new `_preflight_docx_tables` walks all body `w:tbl` nodes, including nested tables, before calling `row.cells`. It counts cumulative rows and expanded cells across nesting, preflights nested `w:gridSpan` and row widths, adds `MAX_DOCX_TABLES=200` and `MAX_DOCX_NESTING_DEPTH=8`. New `tests/test_docx_nested_table_limits.py` contains eight generated DOCX scenarios. Accepted plaintext output remains as before: inner table text is not exported.

## Verification / blockers
- **Executed:** local isolated functional probe (python-docx 1.2.0), using real generated DOCX fixtures and the same preflight algorithm, passed **8/8** case categories. This was **not** an exact full GitHub checkout, and **did not** execute the new committed unittest module directly. No claim of full suite/test completion.
- **NOT EXECUTED on exact head:** full Python unittest suite, Mini App Node tests/typecheck/build, Docker, bot/API integration, throughput or load/memory tests. Domain fixture tests in GitHub must run after CI runners recover.
- [GitHub Actions CI blocker #101](https://github.com/Dimash313/FileShape/issues/101) has pre-runner zero-step failures; do not count these as passing. Retain Draft, do not merge until exact-head checks **run and pass**, review is complete and merged-main push CI passes.
- Parser and XML allocation happen before table preflight; worker/host resource isolation and upload/ZIP bounds are still required. New caps can intentionally reject previously accepted very deeply nested tables; performance not benchmarked.
- No shared HTTP/auth/quota/worker code modified; security-owned contract coordination remains required for cross-client behavior changes. No new dependencies or prohibited content.

## Integration / next work
1. Required parent chain: architecture/docs [PR #112](https://github.com/Dimash313/FileShape/pull/112) → #125 → #130 → #146 → #154 → #160. All are unmerged Draft; preserve dependency order, recheck current GitHub statuses and merge only on verified CI.
2. Existing PDF work belongs to [#114](https://github.com/Dimash313/FileShape/pull/114) (malformed/encrypted/size regressions) and [#108](https://github.com/Dimash313/FileShape/pull/108) (HTTP PDF merge). Do not duplicate or alter their shared API contracts.
3. Next: run new tests on the exact GitHub checkout and full repo when runner issue #101 is resolved; inspect nested-table text semantics separately (no fidelity change in #160), profile bounded OOXML parser resource behavior on representative documents and open independent Issues only for confirmed gaps.
