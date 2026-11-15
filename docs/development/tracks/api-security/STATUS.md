# API & security — handoff

Updated: 2026-11-15 UTC; verify live GitHub heads/issues/checks before resuming.
Track: `api-security`.
Current Issue: [#163](https://github.com/Dimash313/FileShape/issues/163), worker stdout stream limit.
Active PR: [#164](https://github.com/Dimash313/FileShape/pull/164) (**Draft**; branch `api-security/163-bounded-worker-stdout`, base `docs/independent-development-tracks` / unmerged PR #112).
Latest code/test commit before this STATUS edit: `c52b6ab38e3bb39a8f881258b4831b05e48b5890` (STATUS commit advances head).

## Current branch changes

- `api/worker_runner.py`: bounded stdout reads, <=16 KiB chunk and 64 KiB+1 byte total sentinel; immediately reject a flooding worker rather than buffering all `proc.communicate()` output. Concurrent input feed, existing wall-clock timeout, Linux process-group termination and child reaping preserved.
- `tests/test_worker_runner.py`: real-process infinite stdout flood rejection and exact output-size JSON boundary; relax existing grandchild-start timeout from 0.7 to 2.0 seconds to avoid failures on slow/cold Python startup while preserving kill verification.
- No `api/server.py`, domain handlers, user auth, accounting/billing, payment, account or external service changes.

**Verification (limited):** a manually reconstructed isolated Linux/Python 3.13 mirror of the changed worker-runner code and tests, with a stub child `api.worker`, ran `python -m unittest discover -s tests -v`: **6/6 passed** after the test timeout adjustment. Initial 0.7s version had **5 passed, 1 existing test failed**. **This was NOT a full repo checkout, exact-GitHub-head CI, Mini App test/build or Docker test.** No unverified production-ready or 10/10 claim.

## P0 GitHub Actions #101 still blocks merges

[Issue #101](https://github.com/Dimash313/FileShape/issues/101): multiple jobs failed before obtaining any runner; recent unrelated [run #43725350075](https://github.com/Dimash313/FileShape/actions/runs/43725350075) has Python/miniapp `runner_id=0`, `steps=[]`. Logs unavailable; annotation text and account usage/policy inaccessible to connector. Owner to inspect run UI and account Actions budgets/policies. No paid overages or bypass. **No Draft PR merge without actual final-head executed Python, Mini App and Docker green tests and review.**

## Independent track PRs and integration

- [#124](https://github.com/Dimash313/FileShape/pull/124) / #120: HTTP Content-Length framing guard.
- [#135](https://github.com/Dimash313/FileShape/pull/135) / #132: design-only ZIP multi-result HTTP extraction; no implemented route, requires domain owner signoff.
- [#142](https://github.com/Dimash313/FileShape/pull/142) / #141: pin published artifact inode/size.
- [#151](https://github.com/Dimash313/FileShape/pull/151) / #147: privacy-safe API route tracing.
- [#156](https://github.com/Dimash313/FileShape/pull/156) / #155: concurrency-safe queue free-slot admission; isolated local model and tests, CI still blocked.
- [#164](https://github.com/Dimash313/FileShape/pull/164) / #163: current bounded worker output.
- PR #87 capability manifest overlaps stacked #107; #108 PDF merge and #109 ZIP create remain unmerged stack dependencies. Each branch has its own STATUS edit; reconcile GitHub Issues/PRs, never blindly overwrite.

## Next

1. Restore hosted Actions runner (#101) and verify full exact-head CI plus Docker and genuine regression tests before merge.
2. Independently review #164 stdout cap, FIFO input/backpressure, timeout/cancellation and process-tree cleanup; rerun with full `api.worker` and Python 3.12.
3. Reconcile dependent branches and STATUS during integration. No public HTTP ZIP-extract route or native website/app implementations in this track yet.
