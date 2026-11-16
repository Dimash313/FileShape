# Images & Archives — handoff

Updated: 2026-11-17 UTC
Track: `images-archives`
Current Issue: [#227 — reject unsupported compression methods during ZIP preflight](https://github.com/Dimash313/FileShape/issues/227)
Branch: `fix/zip-unsupported-compression-j3`; base `fix/zip-pinned-read-extract-j2` ([parent Draft PR #221](https://github.com/Dimash313/FileShape/pull/221)).
New Draft PR: pending creation; inspect GitHub for live head and CI.

## Current branch (not merged)
- `services/archive_tools.py`: validate `ZipInfo.compress_type` in the existing metadata preflight `_validate_member`. Accept all four Python-supported ZIP methods: STORED, DEFLATED, BZIP2, LZMA. Reject unknown methods with a stable `ValueError("Неподдерживаемый метод сжатия ZIP")` **before any extraction / temp stage creation**. Prevents `zip:list` reporting that an undecodable archive is supported while `zip:extract` later fails with `NotImplementedError`.
- `tests/test_zip_compression_methods.py`: three real ZIP tests using synthetic text. Patch local+central header compression ID to `99` (genuine Python metadata parse success, but decoder unsupported); ensure `inspect_zip` rejects; mixed archive with an unknown later member must fail before any member decode, preserve a preexisting destination and leave no temp stages; real ZIP roundtrips for all four supported methods preserve ordered flat names.
- No change to public `ArchiveModulePort`, file count / size / compression-ratio / traversal / encrypted / symlink / special-file handling, CRC checks, no-clobber/atomic extraction, ZIP creation semantics, or any API/bot/worker/Mini App/quota/billing modules. Only synthetic text fixtures; comply with `AGENTS.md`.

## Verification
- Issue and implementation/test code committed on GitHub. **Current branch exact-head Python/Mini App/Docker not yet confirmed.** Do not count prior parent checks as evidence for changed code.
- Parent [PR #221](https://github.com/Dimash313/FileShape/pull/221), final source head `10c6d85732af4677f9f3dd073bdb638dca3affc0`, passed real [Actions #43932287656](https://github.com/Dimash313/FileShape/actions/runs/43932287656): **698/698 Python tests, Mini App tests/typecheck/build, Docker success**. It pins the ZIP source once through inspection/extraction, rejects symlink/FIFO/directory, and preserves no-clobber/CRC rollback.
- Parent [PR #200](https://github.com/Dimash313/FileShape/pull/200) passed 691 Python tests/Mini App/Docker [Actions #43758603926](https://github.com/Dimash313/FileShape/actions/runs/43758603926). #200 pins ZIP source streams through both creation passes and checks size/mtime on open inode; not a complete immutable snapshot.
- API/security still owns live owner workspace isolation, concurrency and worker resource controls. This PR does not enable HTTP ZIP extraction ([Issue #132](https://github.com/Dimash313/FileShape/issues/132), [Draft #135](https://github.com/Dimash313/FileShape/pull/135)).
- No beta or production execution claimed. All changes Draft/unmerged pending actual review, ancestor integration and post-merge main CI.

## Dependency chain
This branch → [#221](https://github.com/Dimash313/FileShape/pull/221) → [#200](https://github.com/Dimash313/FileShape/pull/200) → [#189](https://github.com/Dimash313/FileShape/pull/189) → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture parents.

CTO owns integration/history review [Issue #211](https://github.com/Dimash313/FileShape/issues/211); never force-push or merge out of order.

## Next action
- Run and inspect exact-head GitHub Actions Python (including new ZIP codec cases), Mini App tests/typecheck/build and Docker; fix concrete failures on this branch before independent code review.
- Preserve all parent safety constraints and do not expand advertised ZIP formats or paid features without owner approval.
