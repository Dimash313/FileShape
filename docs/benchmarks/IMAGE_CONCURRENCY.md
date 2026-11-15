# Image-to-PDF concurrency benchmark

Status: **opt-in engineering diagnostic — not a concurrency policy or production SLA**.

Track: Images & Archives. [Issue #178](https://github.com/Dimash313/FileShape/issues/178) / [Draft PR](https://github.com/Dimash313/FileShape/pulls). Follow-up to [Issue #166](https://github.com/Dimash313/FileShape/issues/166) and evidence for API & Security [Issue #177](https://github.com/Dimash313/FileShape/issues/177). This document does **not** authorize or implement changes to worker admission, quotas, paid tiers or API behavior.

## Usage

The script is Linux-only, reads process RSS from /proc and uses the existing image benchmark to execute the **actual** FileShape \`image_module.bundle_as_pdf\` code in separate subprocesses. All inputs are reproducible synthetic solid fills or abstract colored rectangles. Every worker has its **own private temporary directory**.

\`\`\`shell
# Two tiny workers, useful to verify end-to-end sampling:
python benchmarks/image_concurrency.py --workers 2 --profile smoke --fixture-style blocks

# Manual, representative synthetic 1.48-million-pixel workloads:
python benchmarks/image_concurrency.py --workers 2 --profile typical --fixture-style blocks

# Expensive: explicit manual opt-in; do not include in default CI:
python benchmarks/image_concurrency.py --workers 3 --profile near-cap --fixture-style blocks --timeout 120 --memory-mib 1024 --aggregate-memory-mib 1024
\`\`\`

The last command has **three children, each with six 1800×1800-pixel images (19.44 million decoded pixels per job)**. This is a large aggregate workload. Run only when the machine can accommodate it; it is not evidence that FileShape can admit three such user jobs safely.

## Bounds and failure handling

- Only **2 or 3 workers**. Each worker uses 2–8 image sources and preserves the existing 20 MiB per-bundle source-byte and 22-million-pixel budgets.
- Child address space is capped with Linux \`RLIMIT_AS\` (default **1024 MiB per child**, configurable 256–4096 MiB). **This is virtual address space, not a guarantee of a physical RSS cap**.
- A configurable **sampled** aggregate resident-memory threshold (default **1024 MiB**, 256–4096 MiB) aborts and reaps the entire group when an observed sample exceeds it. Sampling can miss transient peaks; this is **not a cgroup or kernel-enforced global hard cap**.
- The monitored child wall deadline defaults to 90 seconds and is configurable 1–600 seconds. It applies **after temporary synthetic fixture generation**. All workers are created with their own process groups, and errors, interruption, threshold violations or timeout result in kill/reap and removal of the temporary fixture/output tree.
- The normal CI regression runs **only two tiny smoke workers** and one controlled failure-cleanup case; neither 3-worker nor near-cap benchmark is automatic.

## What the JSON means

\`peak_sampled_children_rss_mib\` is the **maximum of periodic simultaneous sums** of child /proc resident pages, excluding the benchmark parent, fixture generation, other processes and container overhead. It is a **lower bound** on the true instantaneous peak of these children, not a hard upper bound; brief peaks can occur between samples.

\`sum_individual_peak_rss_mib\` sums each child's self-reported absolute peak RSS (Linux \`resource.getrusage\`); peaks may have occurred at different moments, so this is an upper envelope of the same children's simultaneous peaks, **not a directly observed simultaneous reading**.

\`total_cpu_seconds\` sums child CPU processing time reported by the image benchmark; \`elapsed_seconds\` includes process startup, imports, actual work, sampling and output verification, but not fixture creation. \`sample_count\` and \`sample_interval_ms\` expose sampling frequency. Runtime Python/Pillow versions, profile, style and individual reports are included.

### Results

**No three-worker near-cap measurement has been produced by this PR yet.** Do not copy single-worker values from [IMAGE_RESOURCES.md](IMAGE_RESOURCES.md) into a concurrency result. If an actual CI smoke measurement is available after the current exact-head checks, cite its run and commit here, including the sample's tiny input size and limitations.

## Integration with resource scheduling

API & Security owns real job admission, queue depth, concurrency and cgroup/worker controls (Issue #177). This script is diagnostic only; it does not change these controls or prove any service-level promise.

Next required evidence: multiple runs on a deployment-equivalent host with observable container/cgroup memory, realistic diverse inputs, OOM/cancellation handling, aggregate load and concurrent worker fairness. Decisions must be reviewed across tracks before changing any user-facing allowance.
