# API & security — handoff

Updated: 2026-11-15 UTC; verify live GitHub heads, Issues, PR bases and Actions.
Track: `api-security`.
Current Issue: [#169](https://github.com/Dimash313/FileShape/issues/169), remove inherited API environment secrets from untrusted worker subprocesses.
Current PR: pending creation on this branch, `api-security/169-worker-env-boundary`, to target `api-security/163-bounded-worker-stdout` / [PR #164](https://github.com/Dimash313/FileShape/pull/164).
Dependency: PR #164 is **Draft**, itself based on `docs/independent-development-tracks` / unmerged PR #112. Merge in dependency order; never squash this branch directly to `main` before #164 and base stack are ready.

## Current bounded change

- `api/worker_runner.py`: explicitly allowlist only necessary non-secret locale, PATH, temp/cache environment keys for the conversion worker; do not forward parent `BOT_TOKEN`, cloud keys, internal assertions, `PYTHONPATH`, `LD_PRELOAD` etc. Supply `PYTHON_DOTENV_DISABLED=1` plus safe Python process flags to keep the transitively imported `config.py` from reloading `.env`.
- `tests/test_worker_runner.py`: launch a **real subprocess** with fake sentinel secrets in the parent's environment; assert no inherited secrets and compatible execution. Verify `load_dotenv` refuses to import a fake BOT_TOKEN when the child flag is set.
- `requirements.txt`: raise the existing python-dotenv lower bound from 1.0 to 1.2 because `PYTHON_DOTENV_DISABLED` was only introduced in v1.2.0. No new dependency.
- No changes to user content, HTTP API routes, authorization, billing, external services or media. Environment minimization is defense-in-depth, **not full sandboxing** of local file parser code.

## Validation and release gates

Issue [#101](https://github.com/Dimash313/FileShape/issues/101) is **closed**: owner made FileShape public after consuming the entire private-repo included Actions Compute, and genuine hosted runners resumed. Parent PR #164 exact head `bef8fad55ff9e2e5912aa02fb8fa31f5ae772eb8` has actual green Python, Mini App and Docker checks ([run #43726214310](https://github.com/Dimash313/FileShape/actions/runs/43726214310) attempt 2). This **does not validate the new worker-env change**; require new PR exact-head full Python tests, Mini App test/typecheck/build, Docker build, additional real-file smoke and independent security/integration review before merging.

## Other unmerged track Draft PRs

- [#124](https://github.com/Dimash313/FileShape/pull/124) HTTP upload framing / issue #120, exact-head green on [run #43720956440](https://github.com/Dimash313/FileShape/actions/runs/43720956440) attempt 2.
- [#135](https://github.com/Dimash313/FileShape/pull/135) design-only HTTP ZIP extract result contract / issue #132; independent staged domain implementation prerequisite and signoff needed.
- [#142](https://github.com/Dimash313/FileShape/pull/142) artifact inode/size pinning / issue #141, exact-head green on [run #43722810006](https://github.com/Dimash313/FileShape/actions/runs/43722810006) attempt 2.
- [#151](https://github.com/Dimash313/FileShape/pull/151) privacy-safe API route tracing / issue #147, exact-head green on [run #43723454162](https://github.com/Dimash313/FileShape/actions/runs/43723454162) attempt 2.
- [#156](https://github.com/Dimash313/FileShape/pull/156) bounded queue admission / issue #155, exact-head green on [run #43724105405](https://github.com/Dimash313/FileShape/actions/runs/43724105405) attempt 2.
- [#164](https://github.com/Dimash313/FileShape/pull/164) streaming subprocess stdout limit / issue #163, exact-head green as above.
- [#102](https://github.com/Dimash313/FileShape/pull/102) CI superseded PR cancellation / pip cache is green and unmerged; #112 and underlying architecture Drafts are also unmerged.

Never treat unmerged changes as active `main` features. Each branch modifies this STATUS file; reconcile handoff changes at integration rather than overwriting. No production/10-of-10 claim until full system smoke and reviews.
