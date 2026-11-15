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
- `tests/test_image_resource_benchmark.py`: 3 regression checks for profile budgets, real smoke child/report on Linux, and invalid-timeout rejection. Full near-cap benchmark is opt-in only and **not run in default CI**.
- `benchmarks/__init__.py` marks diagnostic package.
- No modifications to actual image algorithms, API contracts, bot, Mini App, shared quota/worker, auth, billing or marketing. Only abstract solid-color fixtures, complying with AGENTS.md.

## Verification status (distinguish tested from untested)
- Files/benchmarks committed, but **NO measured benchmark numbers claimed** in this handoff. Need actual smoke and near-cap measurements on representative host/OS and repeat for credible variance.
- Owner reported GitHub Actions quota fixed by making repository public. I invoked GitHub rerun of failed workflow **#43725314168** for parent PR #162. GitHub then showed actual runner execution: Mini App job `success`, including install, tests, typecheck and build; Python job was `in_progress` on `Run tests` at last inspection. Unlike old zero-step jobs this is **real progress**, but **not a green combined CI** yet.
- All exact-head Python regression, Mini App, Docker, real bot/API interactions, high-load worker resource benchmarks, and post-merge main CI required before merge. Check the latest #168 GitHub Actions after this docs update; no stale SHA evidence.
- PR #162 had previously 35/35 passing local reconstructed-domain tests, not full exact-head suite.
- No draft merged. Do not infer closure of [issue #101](https://github.com/Dimash313/FileShape/issues/101) until actual required jobs pass.

## Dependency chain
[#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture ancestor PRs.

All remain stacked Draft/unmerged as verified earlier; do not merge out of order, or without actual final-head green checks and independent review.

## Next unblocked action
- Verify #168 Python test/CI and the rerun of #162; fix any concrete failures rather than opening unrelated new feature work.
- Execute opt-in smoke/typical/near-cap benchmarks in representative, bounded worker container and record **actual** measured times/RSS/CPU with hardware/versions. Never change limits from estimated performance.
- Maintain owner-scoped ZIP HTTP extraction API contract coordination with api-security; PR #135 is a proposal, not enabled.
