# PDF & documents — handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.
Current task: [Issue #119](https://github.com/Dimash313/FileShape/issues/119) — DOCX ZIP member path safety.
Active PR: [#125](https://github.com/Dimash313/FileShape/pull/125) **DRAFT**, branch `pdf-documents/119-docx-zip-safety`, base `docs/independent-development-tracks` ([PR #112](https://github.com/Dimash313/FileShape/pull/112)).
Code/tests commit before this handoff: `8075ae328a27ff26ce8f8a333e7d49785d51da74`; verify the **latest** PR head SHA on GitHub after this STATUS update (self-referencing a commit SHA is not stable).

## Implemented on this unmerged branch
- `services/document_tools.py`: reject duplicate (including casefold-equivalent) ZIP member names, absolute/traversal/backslash/drive/control-character paths and symlink entries before python-docx parsing.
- `tests/test_docx_container_safety.py`: generated valid DOCX positive control and negative ZIP member fixtures with absent-output assertions.
- No changes to API contracts, Telegram handlers, quota/auth, document formats, dependencies, payment systems or external integrations.

## Verification and blockers
- **Executed locally on an isolated reconstructed domain/test subset, not an exact GitHub checkout:** `python -m compileall -q services tests` passed; `python -m unittest discover -s tests -p 'test_*doc*.py' -v` **8 passed** (4 new, 4 existing domain tests).
- **NOT EXECUTED on exact PR head:** full Python suite, Mini App tests/typecheck/build, Docker, bot/API integration, real Telegram end-to-end.
- GitHub Actions runner issue [#101](https://github.com/Dimash313/FileShape/issues/101) remains blocking; a zero-step failure is **not** a test pass. Keep PR draft/unmerged.
- Parent architecture chain [#93–#111](https://github.com/Dimash313/FileShape/pulls) and track-doc [#112](https://github.com/Dimash313/FileShape/pull/112) are unmerged. Check base/head relationships and conflicts again before merging.
- Other PDF regression work is owned by [Issue #113](https://github.com/Dimash313/FileShape/issues/113) / [Draft PR #114](https://github.com/Dimash313/FileShape/pull/114), which must not be duplicated.
- Shared API/security/worker contracts remain owned by `api-security`; PDF merge API [#108](https://github.com/Dimash313/FileShape/pull/108) must be reviewed with that track.

## Next work
1. Run exact-head `python -m unittest discover -s tests -v`, Mini App checks and Docker when CI runners recover; verify DOCX/TXT output and error behavior through bot/API.
2. After #119 review/merge, open an independent Issue for DOCX malformed relationships/XML error handling or bounded parse resources **only if** not already covered by a live PR. No unsupported code/throughput claims.
