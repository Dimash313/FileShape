# PDF & Documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.

Current Issue: [#184 — atomic DOCX/TXT output publication](https://github.com/Dimash313/FileShape/issues/184).
Active branch: `pdf-documents/184-atomic-document-output`, based on `pdf-documents/157-nested-table-quotas` / [Draft #160](https://github.com/Dimash313/FileShape/pull/160).
Code and new tests commit: `b8c321c26bc17eb4518ad458305034a8bf5e9c1e`. STATUS edit changes branch head; query GitHub for final exact SHA.

## Current domain work (not merged)
- [PDF Draft #114](https://github.com/Dimash313/FileShape/pull/114): malformed/encrypted and over-limit regression coverage. Exact-head GitHub CI green.
- [PDF Draft #183](https://github.com/Dimash313/FileShape/pull/183): `pdf_tools.py` atomically stages outputs for PDF extract/rotate/merge/remove and cleans partial writes; exact-head workflow [#43735109267](https://github.com/Dimash313/FileShape/actions/runs/43735109267) finished success on both `tests` (Python/Docker) and `miniapp` (npm tests/build). No independent formal review yet. Base #114.
- DOCX Drafts [#125](https://github.com/Dimash313/FileShape/pull/125) (ZIP path safety), [#130](https://github.com/Dimash313/FileShape/pull/130) (malformed OOXML), [#146](https://github.com/Dimash313/FileShape/pull/146) (table/text budgets), [#154](https://github.com/Dimash313/FileShape/pull/154) (vertical merges), and [#160](https://github.com/Dimash313/FileShape/pull/160) (nested table budgets) each had exact-head CI green. All remain Draft/unmerged.
- **Issue #184 / new domain branch:** `document_tools.py` adds `_write_document_atomically`, using same-directory mode-0600 temporary files and `os.replace` after successful write/close. `docx_to_txt` and `txt_to_docx` now publish complete outputs without clobbering an existing result on write or publish failures. Existing output symlink is replaced, not followed. `tests/test_document_atomic_output.py` adds eight real-generated DOCX/TXT and fault-injection tests. No action names/metadata/quotas, dependency, shared API/worker/Telegram/UI changes.

## Validation / blockers
- Reproduced old direct `document.save(str(target))` fault locally: a partial output after `OSError` replaced previous bytes, proving the gap.
- Verified python-docx 1.2.0 can save a generated DOCX directly to a binary file-like stream, enabling the staging mechanism.
- **Not yet verified at status creation:** new committed test module on exact head, full repository unittest, Docker and Mini App. GitHub Actions must execute all tests and go green before any merge, and actual independent review is required.
- Github runner allocation issue [#101](https://github.com/Dimash313/FileShape/issues/101) is closed, but this does not waive CI.
- Target directory is server-controlled/private; helper cannot guarantee safety if attacker has write access to that directory. Atomic rename gives visibility atomicity, not power-loss durability (no fsync guarantee).

## Integration plan
1. Parent architecture sequence [#93–#112](https://github.com/Dimash313/FileShape/pull/112) must integrate after CTO/security review and main-push CI. Governance PRs #91/#92 are also green but separate.
2. PDF branch: #114 → #183, independently.
3. DOCX branch: #125 → #130 → #146 → #154 → #160 → Issue #184 Draft PR after passing full exact-head CI.
4. Review domain errors, symlink/path ownership, real DOCX/TXT fixture behavior and cleanup before shipping. Do not force-merge or claim 10/10 based solely on green checks.
