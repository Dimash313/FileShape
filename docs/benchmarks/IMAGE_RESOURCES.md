# Image and multi-page PDF resource measurements

Status: **engineering benchmark evidence, not a production SLA**.
Track: `images-archives`; [Issue #166](https://github.com/Dimash313/FileShape/issues/166), [Draft PR #168](https://github.com/Dimash313/FileShape/pull/168).
Run: [GitHub Actions #43730150700](https://github.com/Dimash313/FileShape/actions/runs/43730150700) on commit `89c84feb60a6d13bec28b7bd73e042fae9878010` (before subsequent documentation edits).

## First measured sample — `smoke`

The image resource test ran a **real** isolated child process calling FileShape's `image_module.bundle_as_pdf`. The parent produced private neutral colored fixtures in a temporary directory; no user files were used. Result was emitted in the job log as `IMAGE_BENCHMARK_SMOKE_JSON`.

| Field | Measured |
| --- | ---: |
| Python / Pillow / OS | 3.12.16 / 12.3.0 / Linux |
| Input formats | PNG + WebP |
| Input pixel count | 15,232 |
| Total encoded input bytes | 383 |
| Output PDF bytes | 2,920 |
| Output pages | 2 |
| Elapsed processing time | 0.025771 seconds |
| Process CPU time | 0.025767 seconds |
| Absolute child peak RSS | **25.785 MiB** |
| Child virtual-address-space limit | 1,024 MiB |

This is **one sample** on a GitHub-hosted CI runner. RSS is the peak of the *entire child process* including Python/Pillow imports and cannot be read as incremental memory used only by the image operation. It does not include parent fixture creation. OS scheduling, CPU, filesystem caches, Pillow codec implementations and format sizes affect results. A 15k-pixel smoke test is **not representative** of the 22 million-pixel batch limit.

On this same exact-head run, the full **671-test Python suite, Mini App tests/typecheck/build and Docker image build passed**. These are CI checks, not a production performance/load test.

## Reproduce on a Linux worker

```shell
python benchmarks/image_resources.py --profile smoke
python benchmarks/image_resources.py --profile typical --fixture-style blocks
# Large run is opt-in; choose a memory/timeout budget on the actual worker:
python benchmarks/image_resources.py --profile near-cap --fixture-style blocks --memory-mib 1024 --timeout 120
```

Each invocation generates synthetic fixtures and runs `services.image_module.image_module.bundle_as_pdf` in a subprocess; it prints machine-readable JSON for wall time, process CPU, child RSS, input/output byte counts, image count, pages, format choices and runtime versions. Use `--fixture-style solid` (default) or `--fixture-style blocks` (deterministic, abstract colored rectangular pattern). Both use neutral synthetic images, without people or animals. The normal CI smoke test covers both styles; larger profiles remain manual.

The `near-cap` profile has six 1,800×1,800 images (19.44m total pixels) and stays below the current 22m bundle pixel limit and 20 MiB encoded input limit. Do **not** auto-run it in default CI.

## Local exploratory high-pixel measurements — not an exact PR checkout

Additional measurements on **manually reconstructed copies** of the image-domain implementation, not on a full GitHub checkout or a deployed FileShape worker. This local Linux environment used Python 3.13.5, Pillow 12.3.0, pypdf 5.9.0 and a 1,024 MiB child RLIMIT_AS. The benchmark worker reproduced FileShape's PDF composition, with generated fixtures created outside the measured child. Each row represents **three fresh child processes** using the stated profile; times are medians and RSS is the range of absolute process peaks.

| Profile / synthetic style | Total pixels | Encoded source bytes | Median elapsed | Peak child RSS range |
| --- | ---: | ---: | ---: | ---: |
| Typical, single color | 1,478,400 | 14,747 | 0.041875 s | 114.684–114.707 MiB |
| Typical, colored blocks | 1,478,400 | 74,270 | 0.079566 s | 112.883–112.895 MiB |
| Near-cap, single color | 19,440,000 | 148,895 | 0.333588 s | 306.879–306.902 MiB |
| Near-cap, colored blocks | 19,440,000 | 382,842 | 0.317290 s | 295.125–295.133 MiB |

This is **not a production memory budget**: synthetic images compress unusually well, CPU model was not recorded, the module files were copied manually and not fully checked out, and no parallel jobs were simulated. RSS and elapsed time must be remeasured with the exact benchmark CLI on the target Linux worker before interpreting workload limits. In particular, several concurrent high-pixel operations can exhaust memory on a small server; concurrency policy belongs to the API/security and worker tracks, not this diagnostic PR.

## Remaining work and interpretation

- Run typical and near-cap with several repetitions in the deployment-equivalent worker/container; record host CPU, memory ceiling, Python/Pillow versions, elapsed p50/p95 and peak RSS across repetitions. **No deployment-equivalent repeated near-cap results are established by the CI baseline or the local exploratory measurements.**
- Verify cancellation, process timeouts, per-owner resource scheduling, and cross-format workloads under production-like concurrency before raising image limits or claiming 10/10 resource readiness.
- Deployment behavior, platform parity, billing and owner-scoped transport security are separate checks; this benchmark neither enables nor asserts them.
