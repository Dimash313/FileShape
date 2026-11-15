# PDF & documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.
Current Issue: [#140 — bound DOCX table expansion and text budget](https://github.com/Dimash313/FileShape/issues/140).
Active PR: [#146](https://github.com/Dimash313/FileShape/pull/146) (**DRAFT**), head branch `pdf-documents/140-bounded-tables`, base `pdf-documents/129-docx-parse-errors` ([Draft #130](https://github.com/Dimash313/FileShape/pull/130)).
Code/tests commit preceding this STATUS update: `c1d877e87c9215e9ac26fbcf0ffd5eb6b2b5854e`. This file cannot self-record its final SHA; always inspect the latest GitHub branch head before merging.

## Implemented, not merged

- PR [#125](https://github.com/Dimash313/FileShape/pull/125), Issue [#119](https://github.com/Dimash313/FileShape/issues/119): reject DOCX ZIP member paths with traversal/noncanonical separators/duplicates and symlinks. Base `docs/independent-development-tracks` ([#112](https://github.com/Dimash313/FileShape/pull/112)).
- PR [#130](https://github.com/Dimash313/FileShape/pull/130), Issue [#129](https://github.com/Dimash313/FileShape/issues/129): normalize corrupt OOXML parse exceptions to a stable `ValueError` without leaking private paths. Base `pdf-documents/119-docx-zip-safety`.
- PR **[#146](https://github.com/Dimash313/FileShape/pull/146)**, Issue [#140](https://github.com/Dimash313/FileShape/issues/140): in `services/document_tools.py` enforce 5,000 cumulative table rows / 20,000 expanded grid cells / 64 cells per row; preflight `w:gridSpan` before `row.cells` can allocate excessively; check the 700,000-character budget cell by cell before constructing a large row. `tests/test_docx_table_limits.py` contains six generated DOCX real-file/boundary cases including malicious `w:gridSpan=1000000`; output and existing account semantics unchanged for valid input. These limits intentionally reject unusually complex tables.

## Verification

- **Executed on local, isolated source-faithful DOCX domain subset (NOT full repo):** `python -m compileall -q services tests` **passed**; `PYTHONPATH=. python -m unittest discover -s tests -p 'test_*doc*.py' -v` **17/17 passed** (6 new #140 + 3 #130 + 4 #125 + 4 original document tests); Python 3 with python-docx 1.2.0. Git blob hashes for source `6696d9cca277cf53ee53d9e14a203dccaf33f227` and new test `214983ea648d2ae3dfeb31f7d91a82aa3c168a74` match the GitHub branch exactly.
- **NOT EXECUTED:** full exact-head Python suite, Mini App tests/typecheck/build, Docker build, bot/API integration or realistic load/performance. Do not claim 10/10 or launch readiness.
- GitHub Actions [Issue #101](https://github.com/Dimash313/FileShape/issues/101) remains a CI/merge blocker. Zero runner steps do not count as tests. Keep PRs draft/unmerged and verify exact head after any changes.

## Dependencies / risk / next tasks

- Integrate strictly in parent order: architecture/ZIP/docs stack → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#125](https://github.com/Dimash313/FileShape/pull/125) → [#130](https://github.com/Dimash313/FileShape/pull/130) → [#146](https://github.com/Dimash313/FileShape/pull/146). Require explicit review and successful exact-head CI for each, then main push CI.
- Other work is owned by PDF regression [#114](https://github.com/Dimash313/FileShape/pull/114) and HTTP PDF merge [#108](https://github.com/Dimash313/FileShape/pull/108). Never modify shared HTTP/auth/quota/worker code without `api-security` coordination.
- Next unclaimed audit: deeply vertically merged DOCX cells and malicious XML complexity; exercise representative load/memory cases, log an Issue for confirmed gaps, avoid another speculative PR. DOCX still loads the OOXML parser before table guards, so the new table caps do not replace runtime worker resource limits.
