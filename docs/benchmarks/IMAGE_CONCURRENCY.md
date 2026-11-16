# Image-to-PDF concurrency benchmark

Status: **opt-in engineering diagnostic — not a concurrency policy or production SLA**.

Track: Images & Archives. [Issue #178](https://github.com/Dimash313/FileShape/issues/178) / [Draft PR #181](https://github.com/Dimash313/FileShape/pull/181). Follow-up to [Issue #166](https://github.com/Dimash313/FileShape/issues/166) and evidence for API & Security [Issue #177](https://github.com/Dimash313/FileShape/issues/177). This document does **not** authorize or implement changes to worker admission, quotas, paid tiers or API behavior.

## Usage

The script is Linux-only, reads process RSS from /proc and uses the existing image benchmark to execute the **actual** FileShape `image_module.bundle_as_pdf` code in separate subprocesses. All inputs are reproducible synthetic solid fills or abstract colored rectangles. Every worker has its **own private temporary directory**.

```shell
# Two tiny workers, useful to verify end-to-end sampling:
python benchmarks/image_concurrency.py --workers 2 --profile smoke --fixture-style blocks

# Manual, representative synthetic 1.48-million-pixel workloads:
python benchmarks/image_concurrency.py --workers 2 --profile typical --fixture-style blocks

# Expensive: explicit manual opt-in; do not include in default CI:
python benchmarks/image_concurrency.py --workers 3 --profile near-cap --fixture-style blocks --timeout 120 --memory-mib 1024 --aggregate-memory-mib 1024
```

The last command has **three children, each with six 1800×1800-pixel images (19.44 million decoded pixels per job)**. This is a large aggregate workload. Run only when the machine can accommodate it; it is not evidence that FileShape can admit three such user jobs safely.

## Bounds and failure handling

- Only **2 or 3 workers**. Each worker uses 2–8 image sources and preserves the existing 20 MiB per-bundle source-byte and 22-million-pixel budgets.
- Child address space is capped with Linux `RLIMIT_AS` (default **1024 MiB per child**, configurable 256–4096 MiB). **This is virtual address space, not a guarantee of a physical RSS cap**.
- A configurable **sampled** aggregate resident-memory threshold (default **1024 MiB**, 256–4096 MiB) aborts and reaps the entire group when an observed sample exceeds it. Sampling can miss transient peaks; this is **not a cgroup or kernel-enforced global hard cap**.
- The monitored child wall deadline defaults to 90 seconds and is configurable 1–600 seconds. It applies **after temporary synthetic fixture generation**. All workers are created with their own process groups, and errors, interruption, threshold violations or timeout result in kill/reap and removal of the temporary fixture/output tree.
- The normal CI regression runs **only two tiny smoke workers** and one controlled failure-cleanup case; neither 3-worker nor near-cap benchmark is automatic.

## What the JSON means

`peak_sampled_children_rss_mib` is the **maximum of periodic simultaneous sums** of child /proc resident pages, excluding the benchmark parent, fixture generation, other processes and container overhead. It is a **lower bound** on the true instantaneous peak of these children, not a hard upper bound; brief peaks can occur between samples.

`sum_individual_peak_rss_mib` sums each child's self-reported absolute peak RSS (Linux `resource.getrusage`); peaks may have occurred at different moments, so this is a separate aggregate of self-reported maxima, **not a directly observed simultaneous reading**. Linux `/proc` sampling and `resource.ru_maxrss` accounting can differ slightly; therefore **the summed values are not a strict numerical upper bound** for independently sampled RSS.

`total_cpu_seconds` sums child CPU processing time reported by the image benchmark; `elapsed_seconds` includes process startup, imports, actual work, sampling and output verification, but not fixture creation. `sample_count` and `sample_interval_ms` expose sampling frequency. Runtime Python/Pillow versions, profile, style and individual reports are included.

### Results

**CI smoke — actual GitHub Actions #43734472561**, checked on commit `12422e4bca5757ef90e321879a941cdfdebd2d12` (before later documentation and test changes): Python 3.12.16, Pillow 12.3.0, Linux. Two parallel workers each processed two 15,232-pixel generated PNG/WebP block images. The **peak simultaneously sampled child RSS** was **54.562 MiB**; the separate sum of child self-reported absolute peaks was **55.688 MiB**. Total process-group elapsed **0.093674 s** and sum of *processing-only* child CPU times **0.052433 s**, 10 RSS samples at 10 ms. Each child successfully published a two-page PDF. The workflow completed **678 Python tests, Mini App tests/typecheck/build and Docker build successfully**. These tiny CI measurements do not establish server capacity for full-size files.

**Local near-cap investigation (not production or exact GitHub checkout):** manually reconstructed copies of the relevant GitHub service and diagnostic modules, Linux Python 3.13.5 / Pillow 12.3.0 / pypdf 5.9.0, host CPU AMD EPYC 9V74, container cgroup 4 GiB memory and a 4-CPU quota. Each worker processed six 1,800 × 1,800 synthetic abstract block images (19.44m input pixels per worker). Three fresh-process repetitions per scenario, sampled every 10 ms, with 1,024 MiB RLIMIT_AS per child and a 2,048 MiB sampled aggregate abort threshold:

| Concurrent jobs | Peak sampled child RSS, range | Aggregate elapsed, median (range) | Per-job source pixels |
| --- | ---: | ---: | ---: |
| 2 | 592.906–592.969 MiB | 1.218 s (1.129–1.252) | 19.44 million |
| 3 | 889.320–889.434 MiB | 1.378 s (1.305–1.439) | 19.44 million |

These are **child-only sampled** resident memory figures; they exclude the benchmark parent, fixture generation, bot, API, database and other container services. They do not predict memory use with photographic/user content. A fourth local run of three near-cap workers with the sampled aggregate abort threshold reduced to 512 MiB exited with `Sampled child RSS exceeded aggregate budget`; the diagnostic removed all `fileshape_concurrency_*` temporary directories. This confirms the tool's cooperative stop behavior in this environment, **not a kernel-enforced hard memory ceiling or complete OOM safety**.

Data were measured in the current local execution environment and must be remeasured using an exact GitHub checkout on a deployment-equivalent worker. Do not promote these sample numbers to production limits.

## Integration with resource scheduling

API & Security owns real job admission, queue depth, concurrency and cgroup/worker controls (Issue #177). This script is diagnostic only; it does not change these controls or prove any service-level promise.

Next required evidence: multiple runs on a deployment-equivalent host with observable container/cgroup memory, realistic diverse inputs, OOM/cancellation handling, aggregate load and concurrent worker fairness. Decisions must be reviewed across tracks before changing any user-facing allowance.
