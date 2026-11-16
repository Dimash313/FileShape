# Images & Archives — handoff

Updated: 2026-11-16 UTC
Track: `images-archives`
Active Issue: [#215 — pin ZIP inspection/extraction input](https://github.com/Dimash313/FileShape/issues/215)
Branch: `fix/zip-pinned-read-extract-j2`
Draft PR: [#221](https://github.com/Dimash313/FileShape/pull/221), stacked on [#200](https://github.com/Dimash313/FileShape/pull/200) (`fix/zip-pinned-create-inputs-j1`). Inspect live final head/CI before integration.

## Implemented in this branch (not in main)
- `services/archive_tools.py`: `inspect_zip` opens a regular source through the already-tested `_open_zip_source` guard (no symlink traversal, no FIFO blocking, `fstat` regular-file requirement), then validates metadata from the pinned `ZipFile` handle. `unpack_zip` opens each ZIP **once**, uses `_inspect_open_zip` for the same real archive handle, and retains that handle throughout entry validation, CRC/byte-budget reading, private stage preparation and no-clobber publication. Never reopens the source path between header and decode.
- `tests/test_archive_extraction_cleanup.py`: preserve the old adversarial regular-path swap test, but assert that a malicious replacement *after preflight* cannot substitute its contents: the original approved ZIP is unpacked, and a subsequent independent inspection rejects the malicious replacement. Test was not dropped.
- `tests/test_zip_pinned_read.py`: 6 tests for source symlinks, FIFO, directories, one pinned open for inspect/extract, ordinary real two-file extraction and no descriptor leakage across repeated corrupt archives. Fixtures contain only synthetic text.
- Existing ZIP count/ratio/size/traversal/encryption protections, safe flat names, CRC failure behavior, no-clobber staged rollback and public ArchiveModulePort unchanged. No new API, worker, quota, payment, Telegram, Mini App or dependencies. `AGENTS.md` remains mandatory.

## Verification and limitations
- Parent [PR #200](https://github.com/Dimash313/FileShape/pull/200) latest inspected head `b58cfd71854c2d1a23a8b167eb8c132d44fa7179` passed **691/691 Python tests, Mini App and Docker** [Actions #43758603926](https://github.com/Dimash313/FileShape/actions/runs/43758603926) following the ctime false-positive correction. This confirms parent only.
- The new branch has not yet completed exact-head GitHub Actions; new regression coverage was authored on GitHub, not claimed as executed until the workflow runs. Must verify Python suite, Mini App tests/typecheck/build, Docker, and port integration before merge.
- Source inode pinning stops pathname substitution but does not prevent **concurrent in-place mutation** by a process that can write the same inode. ZIP CRC/declared size checks detect many corrupt changes, not a cryptographic immutable snapshot. Owner workspace isolation and worker resource quotas remain separate responsibilities of API & Security.
- No beta, production deployment or merged main integration claimed. No changes to source/bundle quotas or ZIP format policy.

## Dependency and integration
Current branch → [#200](https://github.com/Dimash313/FileShape/pull/200) → [#189](https://github.com/Dimash313/FileShape/pull/189) → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture ancestors.

CTO [Issue #211](https://github.com/Dimash313/FileShape/issues/211) tracks duplicated architecture-test Git history in middle ancestors. This is integration housekeeping, not evidence of a source-text conflict; all ancestors require review and exact-head successful CI.

## Next
- Verify new ZIP source tests and full exact-head GitHub Actions. Fix real failures without deleting negative cases.
- Wait for parent integration and CTO review before any merge; preserve ZIP API extraction contract [Issue #132](https://github.com/Dimash313/FileShape/issues/132) as a proposal only.
