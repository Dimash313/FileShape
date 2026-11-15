# PDF & Documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.

Current Issue: [#193 — validate malformed DOCX row offsets and merge values](https://github.com/Dimash313/FileShape/issues/193).
Active Draft PR: [#194](https://github.com/Dimash313/FileShape/pull/194); head `pdf-documents/193-validate-row-grid`; base `pdf-documents/184-atomic-document-output` ([Draft #187](https://github.com/Dimash313/FileShape/pull/187)).
Code/test commit before this STATUS update: `2989e2c2fb3a10fa09c62329ea23fa3d6e04818d`. This STATUS update advances the branch SHA; always inspect the latest GitHub head when checking CI or merging.

## New scoped hardening on unmerged branch
- [#194](https://github.com/Dimash313/FileShape/pull/194) / [Issue #193](https://github.com/Dimash313/FileShape/issues/193): `services/document_tools.py` validates both OOXML row grid offsets before `row.cells` expansion; normalizes lazy integer-parsing errors to `ValueError("Повреждённая таблица DOCX")`, rejects negative/oversized offsets and before+cellspan+after exceeding table width, and rejects unknown `w:vMerge` states. The check includes nested tables. `tests/test_docx_row_attributes.py` adds nine real generated DOCX fixtures: valid ordinary and skipped-column rows, malformed offsets, negative/huge offsets, invalid horizontal layout, unexpected vertical merge values and nested rows. Accepted plaintext export semantics unchanged.
- Reproduction before fix: python-docx 1.2.0 accepted a DOCX with `w:gridBefore w:val="not-an-integer"` during `Document(path)`, then raised raw `ValueError` only when `row.grid_cols_before` was accessed. This was outside existing corrupt-package exception normalization.

## Related, currently unmerged PDF work
- [#114](https://github.com/Dimash313/FileShape/pull/114) / Issue #113: real PDF malformed/encrypted/oversized regression tests.
- [#183](https://github.com/Dimash313/FileShape/pull/183) / Issue #182: atomic output publication for PDF extract/rotate/merge/remove. [Workflow #43735109267](https://github.com/Dimash313/FileShape/actions/runs/43735109267) passed real full Python unittest/Docker and Mini App jobs on exact head. Remains Draft pending reviews/parents.

## Related, currently unmerged DOCX work
- [#125](https://github.com/Dimash313/FileShape/pull/125): unsafe OOXML ZIP member path/duplicate/symlink rejection.
- [#130](https://github.com/Dimash313/FileShape/pull/130): corrupt OOXML package parser error normalization.
- [#146](https://github.com/Dimash313/FileShape/pull/146): bounded table expansion and incremental text budget.
- [#154](https://github.com/Dimash313/FileShape/pull/154): vertical merge depth and structure validation.
- [#160](https://github.com/Dimash313/FileShape/pull/160): nested tables share cumulative resource quota.
- [#187](https://github.com/Dimash313/FileShape/pull/187) / Issue #184: atomic DOCX/TXT output staging and cleanup. Exact-head [workflow #43736864001](https://github.com/Dimash313/FileShape/actions/runs/43736864001) completed **success** for both full Python unittest/Docker and Mini App jobs. Remains Draft/unmerged.
All preceding PDF and DOCX PRs in this handoff have passing exact-head GitHub Actions but lack independent review and parent integration.

## Verification / blockers
- For Issue #193, **confirmed locally** malformed offset reproduction via generated DOCX and python-docx 1.2.0, without executing FileShape committed tests before PR creation.
- **Not yet verified for #194 at status creation:** new 9-test module, exact-head full Python unittest suite, Mini App npm tests/typecheck/build and Docker. Wait for GitHub Actions actual execution; failure requires code/test correction and rerun.
- [CI runner Issue #101](https://github.com/Dimash313/FileShape/issues/101) is closed after runner recovery. Its closure does not waive exact-head CI, review, or merged-main CI.
- Server-controlled private workspaces remain a required boundary for atomic output; no new dependencies or prohibited content. This patch does not change API, auth, quotas, workers or other tracks.

## Integration order / next
1. CTO/maintainer review and safely integrate governance PRs #91/#92 and architecture/docs #93→#112 with main-push CI between changes; review conflicts and dependency bases.
2. DOCX: #125→#130→#146→#154→#160→#187→#194. PDF: #114→#183. Do not merge out of order, use forced merging, or claim production readiness without acceptance and integration tests.
3. Verify #194 exact-head GitHub Actions, then resolve any real test failures in the same PR; keep feature-scope and status accurate.
