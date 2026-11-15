# PDF & Documents — GitHub-first handoff

Updated: 2026-11-16 UTC. Track: `pdf-documents`.

Current Issue: [#209 — regular DOCX/TXT source descriptors](https://github.com/Dimash313/FileShape/issues/209).
Current branch `pdf-documents/209-regular-input-files`, based on `pdf-documents/203-pinned-docx-source` / [Draft #205](https://github.com/Dimash313/FileShape/pull/205).
Source/test commits before STATUS edit: `00e03018760c4deb3486e99d49da681cc18104d5`, `55b812049ad1968526113feb5dccee46d5a8eab7`, `0402262af829f82d42a813695174fcfd906e8c9b`. The status update advances the branch head; query GitHub for final SHA.

## Focused security hardening (Issue #209)
- Reproduced in Linux/Python 3.13/python-docx 1.2.0: existing `source.open("rb")` follows a DOCX symlink and parses the referenced private text; secure `os.open(..., O_NOFOLLOW)` rejects the same symlink with `ELOOP`. On Linux `os.open(..., O_NONBLOCK)` plus `fstat` can detect a FIFO as nonregular without blocking for writers. This is defense-in-depth; a caller must still own the workspace.
- `services/document_tools.py` adds `_open_regular_input`: Linux/POSIX no-follow and nonblocking opening, `os.fstat` requiring a regular inode, robust `fdopen` ownership and cleanup. A platform without `O_NOFOLLOW` uses a best-effort `Path.is_symlink()` check, **not equivalent** to atomic no-follow protection.
- Used by `read_docx_text` (the same pinned descriptor continues from ZIP checks through python-docx parsing as in #205), `read_plain_text` (retains actual bounded `MAX_TEXT_BYTES+1` read) and `validate_docx(Path)`. Open stream form `validate_docx(BinaryIO)` remains supported and does not close caller stream.
- New `tests/test_document_regular_inputs.py` has nine real generated DOCX/TXT tests for successful conversions, input symlinks and dangling symlinks, FIFO, directory, absent source, stream validator compatibility, corrupt ZIP and no rejected outputs.
- Updated `tests/test_txt_read_boundaries.py` growth-race simulation to mutate the opened regular file **after** the new secure descriptor opener, retaining its precise 2MiB byte cap regression instead of accidentally disabling the test.
- No shared API, Telegram, payments, worker/quota changes, external services, imagery, music, advertisements or content changes. No new dependency.

## Existing unmerged but exact-head green work
- PDF: [#114](https://github.com/Dimash313/FileShape/pull/114) malformed/limit regression → [#183](https://github.com/Dimash313/FileShape/pull/183) atomic PDF publication.
- DOCX stack: [#125](https://github.com/Dimash313/FileShape/pull/125) ZIP member safety → [#130](https://github.com/Dimash313/FileShape/pull/130) error normalization → [#146](https://github.com/Dimash313/FileShape/pull/146) table quotas → [#154](https://github.com/Dimash313/FileShape/pull/154) vertical merges → [#160](https://github.com/Dimash313/FileShape/pull/160) nested-table limits → [#187](https://github.com/Dimash313/FileShape/pull/187) atomic DOCX/TXT outputs → [#194](https://github.com/Dimash313/FileShape/pull/194) malformed row offsets → [#199](https://github.com/Dimash313/FileShape/pull/199) real 2MiB TXT byte bound → [#205](https://github.com/Dimash313/FileShape/pull/205) single pinned DOCX source across validation/parse.
- Draft #205 current HEAD `ae8e72d34b4e61926330db1a96af12cc61309e07`: [run #43757545127](https://github.com/Dimash313/FileShape/actions/runs/43757545127) had both jobs completed `success` with Python compile/unittest/Docker and Mini App npm test/build. All above track heads green, but unreviewed and unmerged.

## Verification and blockers
- **Executed** local real-file proof of the symlink-follow behavior and Linux `O_NOFOLLOW` denial; FIFO `fstat` classification. This is not an exact-head committed test run.
- **Not yet executed on this new branch at STATUS creation:** full repo unittest, new nine-test module, Mini App npm test/build, Docker. Require real exact-head GitHub Actions and independently review error/portability/owner boundaries.
- The helper does not protect against in-place mutation of an opened inode or untrusted parent-directory traversal; only server-owned private workspace paths are supported. There is no filesystem snapshot or user-to-user auth implemented in this domain. File ownership/auth remains at ingress/application boundary.
- Governance #91→#92 and architecture/docs #93→#112 require independent CTO/security review and sequential main-push CI before domain PRs can merge. CI Issue #101 is closed; no CI waiver.

## Next steps
1. Open Draft PR for Issue #209 on top of #205; verify exact changed files and GitHub Actions. Fix all new test failures in same PR, document actual exact head.
2. Obtain independent review, integrate parents sequentially, verify merged-main push CI and user-facing owner/temp-file isolation before declaring production readiness.
