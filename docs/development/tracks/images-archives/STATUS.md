# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Claimed Issue: [#166 — isolated image resource benchmark](https://github.com/Dimash313/FileShape/issues/166)
Current branch: `test/image-resource-benchmarks-h7`
Active PR: [#168](https://github.com/Dimash313/FileShape/pull/168), **Draft** based on PR #162 (`fix/image-pinned-inputs-h6`).
Implementation/test snapshot before status update: `a9b7bceac87c33291cf5e7aefe0b5144eb7773ce`; inspect PR #168 **live** for latest exact head.

## Current Draft work (#168, not merged)
- `benchmarks/image_resources.py`: opt-in deterministic Linux benchmark of real image-domain `image_module.bundle_as_pdf` using generated geometric JPEG/PNG/WebP. Three profiles: `smoke`, `typical` and `near-cap` (6 × 1800 × 1800 = 19.44m pixels, within 22m batch cap).
- Parent makes fixtures in a private temp directory; isolated child measures wall time, process CPU, and its **absolute total peak RSS** (including imports), with 1024 MiB address-space limit by default and 90-second timeout. Reports actual runtime JSON, versions, input and result sizes; cleans temp directory. Peak RSS figures are platform/hardware-dependent.
- `tests/test_image_resource_benchmark.py`: 5 tests covering profile budgets, deterministic geometric fixture generation, invalid style, two real isolated child smoke profiles on Linux and invalid timeout. Full near-cap benchmarking is opt-in and **not run by default CI**.
- `benchmarks/__init__.py` marks diagnostic package.
- No changes to actual image algorithms, API contracts, bot, Mini App, shared quota/worker, auth, billing or marketing. Fixture styles are `solid` and deterministic abstract `blocks`, with no depictions of living beings; AGENTS.md applies.

## Verification status (distinguish tested from untested)
- **Measured in actual GitHub Actions CI** [run #43730150700](https://github.com/Dimash313/FileShape/actions/runs/43730150700), commit `89c84feb60a6d13bec28b7bd73e042fae9878010`: **671 Python tests passed**, Mini App passed, and Docker build passed. Embedded isolated `smoke` output (2 PNG/WebP images, 15,232 pixels): wall `0.025771 s`, CPU `0.025767 s`, **absolute child peak RSS `25.785 MiB`** on Linux / Python 3.12.16 / Pillow 12.3.0; synthetic input 383 bytes, PDF 2,920 bytes. This is a **single small workload sample**, not representative performance near the full image limit. Source and methodology: [docs/benchmarks/IMAGE_RESOURCES.md](https://github.com/Dimash313/FileShape/blob/test/image-resource-benchmarks-h7/docs/benchmarks/IMAGE_RESOURCES.md). Three local exploratory runs per `typical` and `near-cap` profile were also performed on manually reconstructed image-domain source copies (NOT an exact repository checkout). Medians: typical `0.041875 s` solid / `0.079566 s` blocks; near-cap `0.333588 s` solid / `0.317290 s` blocks. Absolute child peak RSS: typical `112.883–114.707 MiB` across styles; near-cap `295.125–306.902 MiB` across styles. These synthetic-source figures are **not a deployed-worker SLA**. Details and limitations are recorded in `docs/benchmarks/IMAGE_RESOURCES.md`. Actual deployment-equivalent repeated benchmarks remain pending.
- After repository publicity restored runners, manual rerun **#43725314168** for parent PR #162 completed: Mini App **success**; Python ran **668 tests, 1 failed** (not a runner issue). The failure was an overly precise image-architecture assertion expecting exactly `from services.image_tools import _open_image` despite the additional legitimate `_atomic_image_output` import. Updated the regression to require `_open_image` imported from `services.image_tools` while still forbidding the legacy facade; applied this fix to PR #144 and dependent branches #153/#159/#162/#168. Their subsequent GitHub Actions successfully executed Python tests, Mini App checks and Docker on the inspected heads (#144/#153/#159/#162). The remaining current benchmark PR #168 has since changed to add `blocks` fixtures/tests and documentation, so it needs its own final-head CI.
- All exact-head Python regression, Mini App, Docker, real bot/API interactions, high-load worker resource benchmarks, and post-merge main CI required before merge. Check the latest #168 GitHub Actions after this docs update; no stale SHA evidence.
- PR #162 had previously 35/35 passing local reconstructed-domain tests, not full exact-head suite.
- The Actions runner-allocation [issue #101](https://github.com/Dimash313/FileShape/issues/101) is **closed** after making the repository public and observing real successful jobs. Exact-head verification is still mandatory for each new commit. No Draft PR has been merged by this track.

## Dependency chain
[#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture ancestor PRs.

All remain stacked Draft/unmerged as verified earlier; do not merge out of order, or without actual final-head green checks and independent review.

## Next unblocked action
- Verify final-head CI on #168 after the geometric fixture and documentation commits; the earlier #168 head passed 671 Python tests, Mini App and Docker, but that is not automatically evidence for new commits. Parent #162 had green CI after its regression test repair.
- Execute opt-in typical/near-cap benchmarks using the **exact PR script** inside a representative bounded deployment worker, repeat under concurrent operations and record host CPU/RAM/versions. Local manually reconstructed samples suggest roughly 300 MiB absolute peak memory for a 19.44m-pixel single job, but do not alter shared quota/concurrency settings without API/security review.
- Maintain owner-scoped ZIP HTTP extraction API contract coordination with api-security; PR #135 is a proposal, not enabled.
