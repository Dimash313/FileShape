# PDF & documents — GitHub-first handoff

Updated: 2026-11-15 UTC. Track: `pdf-documents`.

Current Issue: [#182 — atomic PDF output publishing](https://github.com/Dimash313/FileShape/issues/182).
Active PR: [#183](https://github.com/Dimash313/FileShape/pull/183) (**DRAFT**), head `pdf-documents/182-atomic-pdf-output`, base `pdf-documents/113-pdf-negative-regressions` ([Draft #114](https://github.com/Dimash313/FileShape/pull/114)).
Pre-status update code/test commit: `f00895a53e85488cd9976f2e9e4a0601ac6022f7`. Always query GitHub for final exact-head SHA; this status change advances it.

## Changes on unmerged PDF branch
- [#114](https://github.com/Dimash313/FileShape/pull/114) / [#113](https://github.com/Dimash313/FileShape/issues/113): five generated real-PDF regressions for truncated, encrypted, too-many-page and merge overflow inputs, plus valid extraction. Exact-head GitHub Actions ran successfully after runner recovery (Python tests + Docker, Mini App).
- **[#183](https://github.com/Dimash313/FileShape/pull/183) / [#182](https://github.com/Dimash313/FileShape/issues/182):** `services/pdf_tools.py` adds `_write_pdf_atomically`; all four PDF-writing functions now write to a private same-directory temporary file and only publish with `os.replace` after successful close. Cleanup happens even when writer/publish raises; no partially written final PDF. `tests/test_pdf_atomic_output.py` adds seven fault-injection and real PDF tests, including writer failure, publish failure, all four valid operations, symlink target and source==target safety. No public interface/limit changes.

## Related DOCX work (independent branch stack)
- [#125](https://github.com/Dimash313/FileShape/pull/125): reject ambiguous/unsafe DOCX ZIP member paths and symlinks.
- [#130](https://github.com/Dimash313/FileShape/pull/130): normalize corrupt OOXML exceptions.
- [#146](https://github.com/Dimash313/FileShape/pull/146): limit table expansion and incremental text budget.
- [#154](https://github.com/Dimash313/FileShape/pull/154): vertical merge recursive-depth limits.
- [#160](https://github.com/Dimash313/FileShape/pull/160): nested-table cumulative resource quota checks.
All named DOCX Draft PR heads have completed **successful GitHub CI** on 2026-11-15; all still await review and parent integration.

## Verification and merge gates
- **Reproduction executed locally:** with pypdf 5.9.0, simulated writer failure after partial bytes changed a pre-existing `PREVIOUS-RESULT` to `PARTIAL` using the old direct-write pattern.
- **NOT YET VERIFIED:** exact-head #183 new committed test module, full repo Python unit tests, Mini App test/build, Docker build; GitHub Actions for #183 must run and pass before merge. Do not claim local end-to-end passes from the reproduction alone.
- Issue [#101](https://github.com/Dimash313/FileShape/issues/101) has been closed after owner changed repo visibility to public and runners recovered; exact-head GitHub CI must still be verified for every new commit.
- Parent order: architecture [#93–#112](https://github.com/Dimash313/FileShape/pull/112) → PDF #114 → PDF #183. DOCX #125→#130→#146→#154→#160 is a separate branch after #112. Integrate cautiously, check reviews and `main` push CI; do not merge red checks or bypass requirements.
- Domain-only operation using server-controlled target directory. Caller remains responsible for secure workspace/ownership and cleanup; atomic replace does not guarantee fsync-backed power-loss durability. No dependencies, media, payment, new service, or content added.

## Next work
1. Run exact-head #183 unit suite, Mini App and Docker in GitHub Actions; investigate any failures before requesting review.
2. Coordinate independent reviewer/CTO integration starting from #91/#92 and architecture #93, then #114→#183. Rebase dependent branches only when necessary, rerun checks after any changes.
3. Do not silently edit shared API/security/worker/Telegram code; any rollout must honor existing owner and quota invariants.
