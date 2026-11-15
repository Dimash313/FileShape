# API & security — handoff

Updated: 2026-11-15 UTC; inspect live PR head SHAs on each return.
Track: `api-security`.
Current Issue: [#141](https://github.com/Dimash313/FileShape/issues/141) — immutable published single-result artifacts.
Active PR: [#142](https://github.com/Dimash313/FileShape/pull/142) (**Draft**, base `docs/independent-development-tracks` / unmerged [#112](https://github.com/Dimash313/FileShape/pull/112)).
Branch: `api-security/141-artifact-result-identity`.
Code/test commit: `529fc4be72d8f5542737fdae5d8480e6ab52eb47` (this handoff commit advances branch head; inspect PR #142 for exact final SHA).

## Changes on this branch

- `api/artifacts.py`: remember completed result file device, inode and exact size on publication, reject later result-open file replacement or length mutation via fd `fstat`; prevent length mutation during completion metadata scan from silently succeeding.
- `tests/test_artifacts.py`: generated private same-size replacement with `os.replace`, post-completion truncation rejection and preexisting lease reading original bytes through a replaced pathname while quota remains reserved.
- Existing per-boot artifact store remains single-result; this **does not implement** the HTTP ZIP multi-result API. Other routes, auth, pricing, billing, domain code and third-party dependencies unchanged.

**Verification:** GitHub code/test commits created and read back, but full Python unittest, Mini App build/tests, Docker build and production behavior **NOT EXECUTED/NOT VERIFIED**. No runner-executed exact-head success. Identity/size matching does not detect same-inode same-length modifications by a privileged same-UID local actor.

## Critical blocker: Issue #101

[CI infrastructure issue #101](https://github.com/Dimash313/FileShape/issues/101) is still open. Observed independent [run #43722310314](https://github.com/Dimash313/FileShape/actions/runs/43722310314): `tests` and `miniapp` failed with `runner_id=0` and `steps=[]`, before executing checkout. The root cause is unknown; owner must inspect UI annotations, personal GitHub Actions budget and repository Actions/runner policy. Paid overages, payment methods or unsafe CI bypass not authorized. **No merges** while runner allocation is blocked.

## Other open API/security tasks and coordination

- [Issue #120](https://github.com/Dimash313/FileShape/issues/120) / [Draft PR #124](https://github.com/Dimash313/FileShape/pull/124): raw HTTP upload framing rejection; separate branch, unmerged. Do not overwrite its tests.
- [Issue #132](https://github.com/Dimash313/FileShape/issues/132) / [Draft PR #135](https://github.com/Dimash313/FileShape/pull/135): design-only owner-scoped multi-file ZIP extraction API; no runtime route or capability advertisement yet. Review with `images-archives` PR #128 before implementation.
- Draft [#87](https://github.com/Dimash313/FileShape/pull/87) and stacked [#107](https://github.com/Dimash313/FileShape/pull/107) overlap capability discovery. Integration owner must reconcile; #108 PDF merge and #109 ZIP create remain dependent/unmerged.
- Editing this STATUS file on multiple parallel Draft branches will require reconciliation during integration; the live Issue/PR/CI are authoritative.

## Next

1. Restore hosted runner allocation (#101), prove executed exact-head Python, Mini App and Docker checks, review parent stack, then consider merging safe changes in dependency order.
2. Have independent review of #142's inode/size pinning and adversarial tests; verify no legitimate result lifecycle regression under cancellation/expiry/restart.
3. Obtain images/archives agreement on #135 before separate HTTP ZIP extraction implementation. Keep standalone web/mobile applications and FileShape-specific account design in future phases.
