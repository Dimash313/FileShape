# API & security — handoff

Updated: 2026-11-16 UTC; verify live GitHub heads, Issues, PR bases and Actions.
Track: `api-security`.
Current Issue: [#210](https://github.com/Dimash313/FileShape/issues/210), repeated task cancellation must not abandon subprocess reaping.
Current branch: `api-security/210-resilient-worker-reap`. PR pending at this status edit; target exactly `api-security/169-worker-env-boundary` / [Draft #170](https://github.com/Dimash313/FileShape/pull/170).
Dependency chain: current branch → #170 (worker env) → #164 (bounded stdout) → `docs/independent-development-tracks` / #112 (unmerged). Never merge out of order or overwrite parent branches.

## Current issue #210 — bounded fix

- `api/worker_runner.py`: added `_reap_worker` which starts one independent wait task and shields it in a retry loop, preserving the caller's cancellation signal **after** reaping. Previous single `await asyncio.shield(proc.wait())` could be interrupted by repeated `task.cancel()`, completing the caller while the wait remained pending.
- `tests/test_worker_runner.py`: deterministic actual-child regression: gate `proc.wait()` completion, cancel parent twice, assert it cannot finish before reaping is permitted to complete; retain timeout/normal cancellation tests. Initial local reproduction (Linux/Python) showed old single-shield code exits early on second cancel. No new dependency, HTTP API, billing, platform, user content or domain changes.
- **No exact-head hosted CI observed for this branch at the time of status edit.** Require real Python suite, Docker and Mini App checks, independent review of process cleanup semantics and integration with parents before merge.

## Parent issue #169 — isolation of worker secrets

## Parent #170 worker-environment changes (already in this branch's ancestry)

- `api/worker_runner.py`: explicitly allowlist only necessary non-secret locale, PATH, temp/cache environment keys for the conversion worker; do not forward parent `BOT_TOKEN`, cloud keys, internal assertions, `PYTHONPATH`, `LD_PRELOAD` etc. Supply `PYTHON_DOTENV_DISABLED=1` plus safe Python process flags to keep the transitively imported `config.py` from reloading `.env`.
- `tests/test_worker_runner.py`: launch a **real subprocess** with fake sentinel secrets in the parent's environment; assert no inherited secrets and compatible execution. Verify `load_dotenv` refuses to import a fake BOT_TOKEN when the child flag is set. Also exercise real TXT → DOCX and probe a generated silent WAV with FFprobe through the actual restricted-environment subprocess; these compatibility regressions are critical because merely echoing sanitized environment variables does not prove conversions still work.
- `requirements.txt`: raise the existing python-dotenv lower bound from 1.0 to 1.2 because `PYTHON_DOTENV_DISABLED` was only introduced in v1.2.0. No new dependency.
- No changes to user content, HTTP API routes, authorization, billing, external services or media. Environment minimization is defense-in-depth, **not full sandboxing** of local file parser code.

## Validation and release gates

Issue [#101](https://github.com/Dimash313/FileShape/issues/101) is **closed**: owner made FileShape public after consuming the entire private-repo included Actions Compute, and genuine hosted runners resumed. Parent PR #164 exact head `bef8fad55ff9e2e5912aa02fb8fa31f5ae772eb8` has actual green Python, Mini App and Docker checks ([run #43726214310](https://github.com/Dimash313/FileShape/actions/runs/43726214310) attempt 2). PR #170 earlier exact head `eba144cbbe3c68974db9285d8dff38059197d8dc` passed real hosted Python, Mini App and Docker CI ([run #43730516974](https://github.com/Dimash313/FileShape/actions/runs/43730516974)). New real-file tests in [run #43757276570](https://github.com/Dimash313/FileShape/actions/runs/43757276570) found **one of 626 tests in error**, not a converter failure: document export passed, WAV probe completed successfully but the test accessed `result["info"]["seconds"]` instead of the existing API envelope `result["info"]["info"]["seconds"]`. Assertion fixed in code commit `a3ac21bb40da36faad4b29ed195f62e30a73a60c`. Re-run exact-head CI before claiming this hardening is green. Require latest PR head successful full Python tests including TXT→DOCX and silent WAV/FFprobe, Mini App typecheck/build, Docker build and independent security/integration review before merging. Do not treat passing previous-head checks as validating these new tests.

## Other unmerged track Draft PRs

- [#124](https://github.com/Dimash313/FileShape/pull/124) HTTP upload framing / issue #120, exact-head green on [run #43720956440](https://github.com/Dimash313/FileShape/actions/runs/43720956440) attempt 2.
- [#135](https://github.com/Dimash313/FileShape/pull/135) design-only HTTP ZIP extract result contract / issue #132; independent staged domain implementation prerequisite and signoff needed.
- [#142](https://github.com/Dimash313/FileShape/pull/142) artifact inode/size pinning / issue #141, exact-head green on [run #43722810006](https://github.com/Dimash313/FileShape/actions/runs/43722810006) attempt 2.
- [#151](https://github.com/Dimash313/FileShape/pull/151) privacy-safe API route tracing / issue #147, exact-head green on [run #43723454162](https://github.com/Dimash313/FileShape/actions/runs/43723454162) attempt 2.
- [#156](https://github.com/Dimash313/FileShape/pull/156) bounded queue admission / issue #155, exact-head green on [run #43724105405](https://github.com/Dimash313/FileShape/actions/runs/43724105405) attempt 2.
- [#164](https://github.com/Dimash313/FileShape/pull/164) streaming subprocess stdout limit / issue #163, exact-head green as above.
- [#102](https://github.com/Dimash313/FileShape/pull/102) CI superseded PR cancellation / pip cache is green and unmerged; #112 and underlying architecture Drafts are also unmerged.

Never treat unmerged changes as active `main` features. Each branch modifies this STATUS file; reconcile handoff changes at integration rather than overwriting. No production/10-of-10 claim until full system smoke and reviews.
