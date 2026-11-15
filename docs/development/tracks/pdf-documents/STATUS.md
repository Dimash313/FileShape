# PDF & documents — handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.
Current Issue: [#129 — DOCX malformed OOXML parser failures](https://github.com/Dimash313/FileShape/issues/129).
Active PR: [#130](https://github.com/Dimash313/FileShape/pull/130) (**Draft**), branch `pdf-documents/129-docx-parse-errors`, base `pdf-documents/119-docx-zip-safety` ([Draft #125](https://github.com/Dimash313/FileShape/pull/125)).
New code/test commit: `e699795c0429635f23caa572a8dbf900e181002f`. The STATUS update creates a newer PR head; query GitHub for the exact current SHA.

## What changed (only on unmerged branches)

- [#125](https://github.com/Dimash313/FileShape/pull/125) / [Issue #119](https://github.com/Dimash313/FileShape/issues/119): `services/document_tools.py` validates DOCX ZIP member paths, rejects duplicates (including case-insensitive names) and symlinks; `tests/test_docx_container_safety.py` covers malicious ZIP entries and valid roundtrip. Parent #125 is stacked on draft track coordination [#112](https://github.com/Dimash313/FileShape/pull/112).
- [#130](https://github.com/Dimash313/FileShape/pull/130) / [Issue #129](https://github.com/Dimash313/FileShape/issues/129): `read_docx_text` converts known malformed OOXML parser/ZIP exceptions to stable `ValueError("Повреждённый DOCX")` without leaking parser internals; `tests/test_docx_malformed_xml.py` covers broken OOXML XML parts, exception mapping, OS error propagation and valid text export.
- No shared API, Telegram or Mini App interface, quotas, storage, payment, additional dependency, or file-format change.

## Verification and blockers

- **Executed locally in an isolated reconstructed DOCX subset, NOT a full exact GitHub checkout:** `python -m compileall -q services tests` passed; `python -m unittest discover -s tests -v` passed **11/11 domain tests** (4 existing document tools, 4 from parent PR #125, 3 new in #130) with Python 3.13 and python-docx 1.2.0. Real generated DOCX XML corruption fixtures were exercised.
- **NOT EXECUTED on the final head:** complete repository unittest suite, Mini App tests/typecheck/build, Docker, real HTTP/bot integration, Telegram.
- GitHub Actions runner issue [#101](https://github.com/Dimash313/FileShape/issues/101) blocks integration. Runner failures with zero steps do not count as test execution. Leave #125/#130 draft and unmerged pending exact-head successful checks, peer review, parent integration and merged-main CI.
- Existing PDF tests [#113](https://github.com/Dimash313/FileShape/issues/113)/[Draft #114](https://github.com/Dimash313/FileShape/pull/114) and multi-PDF HTTP [Draft #108](https://github.com/Dimash313/FileShape/pull/108) have separate ownership. Do not duplicate or touch shared API/worker contracts without `api-security` approval.

## Next unblocked work

1. When CI runners can start, run full exact-head checks on #125 and #130 and confirm 11 local domain tests against the full repository; inspect possible conflicts with the stacked architecture.
2. Audit DOCX complex-table/per-document text resource bounds and XML relationship behavior; open a separate Issue for an evidence-backed independent gap only after checking live Issues/PRs.
3. Merge dependency order (#112 and parents → #125 → #130), only when reviews and CI pass. No claim of production readiness or measured performance.
