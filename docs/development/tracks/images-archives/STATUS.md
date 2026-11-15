# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Claimed Issue: [#178 — bounded concurrent image PDF resource measurement](https://github.com/Dimash313/FileShape/issues/178)
Current branch: `test/image-concurrent-resources-h8`
Active PR: [#181](https://github.com/Dimash313/FileShape/pull/181), **Draft** based on `test/image-resource-benchmarks-h7` (PR #168). Review live GitHub PR head/CI after documentation changes.

## Work in this branch (not merged)

- `benchmarks/image_concurrency.py`: opt-in Linux diagnostic for **two or three independent processes** using only synthetic solid/block fixtures and existing `image_module.bundle_as_pdf`, with per-worker private directories. Samples simultaneous child-only RSS from /proc; distinguishes sampled aggregate from sum of individual process peaks, reports CPU, wall time, sampled count, exact input sizes and runtime metadata as JSON. Per-child RLIMIT_AS, a sampled aggregate RSS abort budget, timeout, kill/reap and cleanup on failure. These bounds do not replace kernel-enforced cgroup or real worker admission.
- `tests/test_image_concurrency_benchmark.py`: lightweight real **two-worker smoke** and error cleanup, procfs sampling and validation of worker/memory/sampling bounds. No default-CI three-worker or near-cap workloads.
- `docs/benchmarks/IMAGE_CONCURRENCY.md`: exact CLI commands, counter semantics, limitations and opt-in manual workload warning.
- `docs/development/tracks/images-archives/ROADMAP.md`: this isolated diagnostic follow-up. AGENTS.md respected; no living-being test images, audio, billing or new providers.

## Verification / release gates

- Parent [PR #168](https://github.com/Dimash313/FileShape/pull/168) **final head before this branch** `4cd324e804eff4990f773abb5c0b963e8c305970` passed actual GitHub Actions [run #43732178535](https://github.com/Dimash313/FileShape/actions/runs/43732178535) including Python, Mini App and Docker.
- **Verified historical head** `12422e4bca5757ef90e321879a941cdfdebd2d12` on [GitHub Actions #43734472561](https://github.com/Dimash313/FileShape/actions/runs/43734472561): **678 Python tests passed**, Mini App tests/typecheck/build passed, and Docker image build passed. Its real 2-worker smoke (2 sources × 15,232 pixels/job) recorded sampled simultaneous children-only RSS **54.562 MiB**, total wall **0.093674 s**, sum of processing CPU **0.052433 s**, and both PDF results valid. **New later test/documentation commits need their own exact-head CI**.
- Previously verified [run #43730150700](https://github.com/Dimash313/FileShape/actions/runs/43730150700) on parent #168 ran 671 Python tests and measured an isolated two-image **single-worker** smoke (15,232 px) at 25.785 MiB child peak RSS / 0.025771 sec wall time. These are single-worker, not aggregate concurrency figures.
- **Measured locally with a reconstructed source mirror, NOT exact GitHub checkout or production worker:** three independent near-cap (19.44m pixels/job) repetitions, abstract block fixtures, Linux Python 3.13.5/Pillow 12.3.0, 4-GiB container/4-CPU quota, sampled every 10 ms: 2 workers peak simultaneous sampled RSS **592.906–592.969 MiB**, median wall **1.218 s**; 3 workers **889.320–889.434 MiB**, median wall **1.378 s**. A 512 MiB sampled aggregate-threshold test aborted and left no temporary output directories. These figures exclude the parent and other container services and cannot establish a safe production concurrency limit. Full measurement scope and caveats: `docs/benchmarks/IMAGE_CONCURRENCY.md`; previous single-worker figures remain `docs/benchmarks/IMAGE_RESOURCES.md`.
- API & Security [Issue #177](https://github.com/Dimash313/FileShape/issues/177) retains ownership of actual concurrent worker admission / per-owner limits. This PR changes no API, queue, quota, worker, payment, bot, Mini App, or Docker code.
- CI runner blockage [#101](https://github.com/Dimash313/FileShape/issues/101) was closed after the repo became public. Every new exact-head commit still needs real successful CI, review and post-merge main verification.

## Stacked Draft dependency chain

Current branch → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture ancestors.

Do not merge out of order. Next: verify CI for the latest documentation/test head of #181; review sampled RSS vs individual peak accounting, then coordinate deployment-equivalent cgroup memory tests, queue admission and worker limits with API/security Issue #177.
