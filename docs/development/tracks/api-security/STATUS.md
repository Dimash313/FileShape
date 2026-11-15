# API & security — handoff

Updated: 2026-11-15 UTC; consult live GitHub for exact current branch head.
Track: `api-security`.
Current Issue: [#155](https://github.com/Dimash313/FileShape/issues/155), admission waiting-room free-slot burst race.
Active PR: [#156](https://github.com/Dimash313/FileShape/pull/156) (**Draft**, branch `api-security/155-admission-burst-fairness`, base `docs/independent-development-tracks` / unmerged PR #112).
Code + test commit before handoff: `36d67433a2d05bc452068a5751a03f9c199b606a`. The STATUS update itself advances the head.

## Current narrow change

- `api/admission.py`: claim available semaphore permits without first scheduling a separate task; prevents a burst from entering the semaphore wait list uncounted and bypassing `max_waiters`. Preserve existing bounded queued/timeout/cancellation/shutdown paths.
- `tests/test_admission.py`: eight-concurrent-request burst with capacity 1 and `max_waiters=1`, plus `max_waiters=0` acceptance/rejection checks.
- No shared `api/server.py`, worker, domain code, auth, billing, costs, payments or dependencies changed.

**Verified:** GitHub commits created. A **standalone Python 3.13 local concurrency model**, not a full repository checkout, reproduced the old behavior (1 admitted / 7 incorrectly waiting / 0 rejected) and the proposed behavior (1 admitted / 1 waiting / 6 rejected). This is limited supporting evidence, **not proof full branch tests passed**.

## Critical CI blocker #101

[Issue #101](https://github.com/Dimash313/FileShape/issues/101) is still open. [Run #43722956682](https://github.com/Dimash313/FileShape/actions/runs/43722956682) independently checked with both `tests` and `miniapp` failing before runner allocation (`runner_id=0`, `steps=[]`). Root cause not confirmed; repository connector cannot read personal Actions budgets/runner policy or the exact annotation. Owner must inspect GitHub UI, personal Actions usage/budget and repository runner policy; no paid overages or bypass.

## Other API/security Draft PRs (unmerged)

- [#124](https://github.com/Dimash313/FileShape/pull/124) — HTTP upload framing hardening, Issue #120.
- [#135](https://github.com/Dimash313/FileShape/pull/135) — design-only HTTP ZIP extraction multi-file artifact contract, Issue #132; coordinate with images/archives #128.
- [#142](https://github.com/Dimash313/FileShape/pull/142) — pin result inode/size at publication and download, Issue #141.
- [#151](https://github.com/Dimash313/FileShape/pull/151) — privacy-safe route tracing, Issue #147.
- #87 duplicates substantial capability manifest work in architecture #107. Review dependency graph, PDF merge #108, ZIP creation #109 and these independent drafts before merging. Multiple branches each carry a STATUS edit; reconcile the handoff with live GitHub PRs instead of blindly overwriting.

## Next action / release gates

1. Confirm real GitHub-hosted runner starts; inspect budget/settings/annotation with owner; require true exact-head Python suite, Mini App tests/build and Docker build on **every** PR.
2. Independently review #156 for semaphores, starvation/fairness, cancellation/shutdown races and parameter validation. No 10/10 or production-ready claim with incomplete checks.
3. Reconcile stacked PR ancestry and CODE reviews before safe integration. No production/new external apps yet.
