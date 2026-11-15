# PDF & documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.
Current Issue: [#150 — cap vertical merge recursion](https://github.com/Dimash313/FileShape/issues/150).
Active PR: [#154](https://github.com/Dimash313/FileShape/pull/154) **DRAFT**, head `pdf-documents/150-vertical-merge-guard`, base `pdf-documents/140-bounded-tables` ([PR #146](https://github.com/Dimash313/FileShape/pull/146)).
Code/tests commit before status edit: `e98913d348de7e5dbc16ae84d5699a350a25fb25`. This STATUS edit advances the branch SHA. Verify the true final head via GitHub.

## Implemented on unmerged, dependent branches
- [PR #125](https://github.com/Dimash313/FileShape/pull/125) / [#119](https://github.com/Dimash313/FileShape/issues/119): reject dangerous/ambiguous DOCX ZIP member paths, duplicates and symlinks. Stacked on docs [PR #112](https://github.com/Dimash313/FileShape/pull/112) and architecture chain.
- [PR #130](https://github.com/Dimash313/FileShape/pull/130) / [#129](https://github.com/Dimash313/FileShape/issues/129): normalize known malformed OOXML parse exceptions to a stable `ValueError`.
- [PR #146](https://github.com/Dimash313/FileShape/pull/146) / [#140](https://github.com/Dimash313/FileShape/issues/140): bound total table rows, expanded grid cells, row grid width and incremental text length before constructing text; preflight `w:gridSpan`.
- **[PR #154](https://github.com/Dimash313/FileShape/pull/154) / [#150](https://github.com/Dimash313/FileShape/issues/150):** limit vertical merge chains to 128 rows and validate previous row's cell span/column offset before `row.cells` recursively resolves `w:vMerge=continue`. A 1,100-row DOCX previously passed row/cell limits but raised `RecursionError` after ~24 seconds. New `tests/test_docx_vertical_merges.py` has eight real-document tests, including normal merged output, orphan/mismatched continuations and skipped grid columns.

## Verification and remaining limits
- **Executed locally on isolated DOCX subset (not full repository):** `python -m compileall -q services tests` passed; `python -m unittest discover -s tests -v` passed **25/25 tests** (8 new + 17 earlier DOCX tests) with python-docx 1.2.0/Python 3.13. The source SHA `8546a4426652d44b8ecbb57cb407da422edbf01d` and test SHA `d2ad9acc70d7c05a2d43bb5c7fcad0d677669e5b` matched GitHub blob hashes byte-for-byte. These checks do **not** establish production readiness.
- **NOT EXECUTED:** complete exact-head Python suite, Mini App Node tests/typecheck/build, Docker image/build, live Telegram bot/API and load testing.
- GitHub Actions pre-runner blocking [Issue #101](https://github.com/Dimash313/FileShape/issues/101) persists. A zero-step failure is not an executed check. Leave all PRs draft; do not merge without reviewed exact-head green CI and post-merge main push workflow.
- Deep XML parsing and arbitrary OOXML body elements still occur before the table-domain guards; worker-level memory/CPU/time limits remain essential. Very long but otherwise valid >128-row vertical merges are intentionally rejected.
- All domain changes preserve existing accepted DOCX/TXT action interfaces, quota/auth, filenames and text-format semantics; no new dependencies or media, payments, ads, imagery or third parties.

## Integration and next work
1. Integrate architecture/ZIP/docs parents → [#112](https://github.com/Dimash313/FileShape/pull/112) → #125 → #130 → #146 → #154 after verified CI and security review; recheck file overlaps and final head SHAs.
2. Do not duplicate PDF regression [PR #114](https://github.com/Dimash313/FileShape/pull/114) or HTTP PDF merge [PR #108](https://github.com/Dimash313/FileShape/pull/108). API/security owns shared request/worker/auth/quotas; coordinate changes there.
3. Prioritize exact-head full CI, representative DOCX performance measurements, XML/OPC parsing error taxonomy and nested-table resource limits. Open an Issue only for a reproduced gap without an owner PR; no speculative performance promises.
