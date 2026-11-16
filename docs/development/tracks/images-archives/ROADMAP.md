# Track: images & archives — roadmap

**Scope:** images, compression/format transformations, ZIP create/list/extract, archive validation, bomb resistance, safe filenames and format-specific tests. HTTP route/auth contracts are coordinated with API/security.

1. Reconcile image adapter drafts #99–#100, ZIP module drafts #105–#106 and HTTP ZIP creation PR #109 with current main.
2. **ZIP writer/reader compatibility:** issue #110, draft PR #111; preserve external ZIP bomb checks, validate roundtrip and reconcile 50 MiB bot vs 20 MiB HTTP limits. Do not close until real CI and review pass.
3. **ZIP extraction HTTP gap:** design safe bounded owner-scoped multi-result protocol with API/security; do not implement insecure public file links or advertise the feature early.
4. Real-file ZIP safety: symlink/path traversal, encryption, high compression ratio, duplicate names, oversized members, cancellation, timeout and cleanup.
5. Image domain performance and capability parity, with bounded image dimensions/pixel budgets and real benchmark evidence.

Work through Issues and independent PRs. New chat must inspect live PR heads and update STATUS in its own branch.


## ZIP extraction failure cleanup — active stacked draft

- [Issue #121](https://github.com/Dimash313/FileShape/issues/121) / [Draft PR #128](https://github.com/Dimash313/FileShape/pull/128): stage bounded extracted files, reject overwrites/symlink destinations, roll back partially published output after CRC or filesystem failures. Add adversarial tests for archive swapping, actual byte limits, corrupt CRC and ZIP bombs.
- PR #128 is stacked on documentation PR #112, itself based on ZIP compatibility PR #111 and HTTP ZIP creation PR #109; **none of this is merged or deployed** as of 2026-11-15. Do not merge out of order or without successful exact-head CI. See `STATUS.md`.
- This is domain-only work; the owner-scoped multi-result HTTP ZIP extraction contract must be coordinated with `api-security` in a separate Issue/PR.


## Atomic image outputs — active stacked draft

- [Issue #133](https://github.com/Dimash313/FileShape/issues/133) / [Draft PR #137](https://github.com/Dimash313/FileShape/pull/137): ensure JPG, PNG, WebP, PDF conversion and WebP compression publish only a completed result. Private same-directory staging, atomic rename and staged cleanup on encode or publication failure; regression tests for real formats, oversized image headers, corrupted inputs, target preservation, symlinks and permissions.
- PR #137 is based on ZIP cleanup PR #128 (and thus #112 → #111 → #109 → architecture parents). These are **draft/unmerged**, not delivered or deployed. Final-head GitHub CI and integration review are required; blocker #101 remains open.
- Follow-up candidate (not started): `services/image_bundle.py` batch PDF output atomicity; create an independent Issue before implementing. Keep public HTTP/image contract ownership with `api-security`.


## Multi-image PDF atomicity — active stacked Draft

- [Issue #138](https://github.com/Dimash313/FileShape/issues/138) / [Draft PR #144](https://github.com/Dimash313/FileShape/pull/144): use the existing single-image atomic staging helper from PR #137 for 2–8 image PDF composition. A failed save or filesystem publication must not corrupt an existing output or leave staged files. Add regression tests for real page order, partial save, symlink, failed rename, byte and pixel budgets and private permissions.
- Local isolated reconstructed-module test result: **12/12 Python tests passed** (3 existing + 9 new), not the full exact GitHub checkout. Full Python/Mini App/Docker CI, bot/API flows and deployment checks remain unverified; runner blocker #101 remains open.
- **Dependency:** #144 is stacked on #137 → #128 → #112 → #111 → #109 and architecture parents. Keep Draft; merge only in parent order after exact-head green CI and review.


## Pre-decode PDF bundle bounds — active stacked draft

- [Issue #148](https://github.com/Dimash313/FileShape/issues/148) / [Draft PR #153](https://github.com/Dimash313/FileShape/pull/153): inspect all 2–8 input image headers and 20 MiB aggregate file sizes before decoding any pixels. Reject symlink/FIFO inputs, preserve the 35m per-image and 22m cumulative pixel caps, and recheck limits during final conversion. This reduces unnecessary peak decode allocations for batches guaranteed to fail, but is **not** a measured throughput or memory improvement claim.
- Local reconstructed-domain tests: **13 passed** (3 existing + 10 new) with synthetic solid-color images; full exact-head Python/Mini App/Docker and realistic resource benchmarks remain unverified. Runner CI issue #101 still blocks readiness.
- Draft dependency: #153 → #144 → #137 → #128 → #112 → #111 → #109 → prior architecture parents. Review/merge only in dependency order after exact-head checks run and pass; preserve existing API/contracts and AGENTS.md rules.


## Image source format validation — active stacked Draft

- [Issue #158](https://github.com/Dimash313/FileShape/issues/158) / [Draft PR #159](https://github.com/Dimash313/FileShape/pull/159): centralize JPEG/PNG/WebP **actual input encoding** and single-frame validation in the image-domain header path; reuse it during all-image PDF preflight. Reject disguised GIF/TIFF and animated WebP/APNG before pixel decoding. Preserve quotas, bounded image size, output formats, EXIF/alpha handling, and atomic cleanup.
- Locally reconstructed module tests: **29/29 passed** (7 new + 22 prior) across input preflight, PDF bundle creation and atomic publication on Python 3.13.5/Pillow 12.3.0/pypdf 5.9.0, not full repo or exact-head GitHub CI. Issue #101 still blocks CI evidence.
- Stack: #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 → architecture parents. Review/merge in dependency order after actual CI. No new platforms, assets, providers or APIs.


## Pinned image input descriptors — active stacked Draft

- [Issue #161](https://github.com/Dimash313/FileShape/issues/161) / [Draft PR #162](https://github.com/Dimash313/FileShape/pull/162): address the regular-file pathname replacement race between batch header validation and later pixel decoding. Hold each regular input open from admission to decode with `O_NOFOLLOW` / nonblocking and `fstat` checks where supported, keep 2–8 / 20 MiB / 22m pixel safeguards, source format/frame validation and atomic PDF publication.
- Regression: replace an already-approved pathname with a disguised GIF (another regular file) during the header pass; PDF must still use the original opened image and retain page geometry. Check FIFO, symlink, corrupt header and descriptor cleanup.
- **Actual local reconstructed-domain regression:** 35/35 Python tests passed (6 new + 29 existing). This is not full-repo exact-head green CI. GitHub runner issue #101 blocks release.
- Stack: #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 → architecture parents. Keep Draft and merge in dependency order after real CI/review. In-place inode modifications and platforms without `O_NOFOLLOW` need separate threat-model review; do not overclaim comprehensive TOCTOU prevention.


## Measurable image CPU and peak-RSS — opt-in benchmark Draft

- [Issue #166](https://github.com/Dimash313/FileShape/issues/166) / [Draft PR #168](https://github.com/Dimash313/FileShape/pull/168) introduces a reproducible Linux CLI, `python benchmarks/image_resources.py --profile smoke|typical|near-cap` (choose one profile), measuring actual `image_module.bundle_as_pdf` elapsed time, CPU time, and total peak child RSS; bounded subprocess timeout, memory limit and generated synthetic color-block fixtures. It never silently runs near-cap in CI.
- No benchmark results or 10/10 performance claims until the exact script is executed, host/versions noted and multiple runs compared. Typical and near-limit input sizes stay within 20 MiB/22 million pixels; all private temporary fixtures are removed after running.
- GitHub Actions runners became active after repository publicity change; parent #162 Mini App job succeeded on manual rerun #43725314168, Python still executing at last inspection. Re-check exact-head branch CI, do not confuse runner allocation with a successful test suite.
- Stack #168 → #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 → architecture ancestors. All Draft until green exact-head gates/review; no API or billing changes.


## Concurrent image PDF resource evidence — stacked diagnostic Draft

- [Issue #178](https://github.com/Dimash313/FileShape/issues/178) follows [Draft PR #168](https://github.com/Dimash313/FileShape/pull/168): add a **manual opt-in** Linux two-/three-worker benchmark using independent synthetic sources and real FileShape image/PDF processors. Report sampled simultaneous child RSS separately from the non-concurrent sum of per-child peak RSS; these are not equivalent to cgroup memory or production service capacity. Ensure group kill/reap, private temporary cleanup and conservative resource caps.
- CI must run only two tiny smoke workers; 3 near-cap workers are expensive and manual. Distinguish measured results from assumptions; do not introduce application-facing worker admission/quota changes. Actual operational concurrency investigation remains API/security [Issue #177](https://github.com/Dimash313/FileShape/issues/177).
- Parent #168 exact-head CI run #43732178535 passed Python, Mini App and Docker; **the new child branch requires its own exact-head CI**. All changes remain Draft, stacked onto #168 → #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 and architecture parents.


## Eager PDF temporary-buffer release — active stacked Draft

- [Issue #186](https://github.com/Dimash313/FileShape/issues/186): in `services/image_bundle.py`, release decoded original images and temporary RGBA intermediates at the **end of each page** instead of at the end of the full PDF bundle, while keeping finished RGB pages until the PDF encoder completes. Register every new canvas for error cleanup before paste.
- Local reconstructed-domain A/B benchmark (same fixtures, 3 fresh processes/profile): **near-cap absolute child peak ~307 → ~196 MiB (~36.2% reduction)**; typical ~115 → ~106 MiB. These are synthetic single-color local figures, not a deployment throughput/cgroup/RSS guarantee. See `docs/benchmarks/IMAGE_RESOURCES.md`; do not change worker limits or quotas without API/security [Issue #177](https://github.com/Dimash313/FileShape/issues/177) evidence/review.
- Four targeted input lifecycle and error cleanup regressions are committed; **full exact-head CI for this new branch is pending**. Parent [PR #181](https://github.com/Dimash313/FileShape/pull/181) passed 678 Python tests, Mini App and Docker at its head. Stack new branch on #181 → #168 → #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 → architecture parents; no auto-merge.


## Pinned ZIP source creation and rebuild — stacked Draft

- [Issue #197](https://github.com/Dimash313/FileShape/issues/197): `make_zip` opened approved input paths again via `ZipFile.write`, including optional high-ratio fallback. This permits regular-file/symlink pathname substitution after metadata approval. Pin up to five regular source descriptors with `O_NOFOLLOW`/nonblocking/`fstat`, stream bounded chunks to `ZipFile.open(..., 'w')` in both passes, and verify exact length/byte budgets while preserving names, compression policy, timestamps/modes, private atomic result publication and reader compatibility.
- New adversarial regression tests cover path swaps in both passes, mutated input size **and same-size in-place rewrites**, FIFO/symlink, descriptor cleanup and ordinary roundtrip. ZIP input checks now compare opened inode identity, size and nanosecond mtime, intentionally **not ctime** (a rename can update ctime without byte changes), while retaining a bounded chunked writer; this is not a cryptographic immutable snapshot. Existing failed-write regression is redirected to the streaming writer without weakening its assertions.
- Stacked on [Draft #189](https://github.com/Dimash313/FileShape/pull/189) → #181 → #168 → #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 → architecture parents. PR #189 needs reconciliation with the newer #181 parent before merge. Run real **exact-head CI** and review; no automatic merging.


## ZIP read/inspection descriptor pinning — new stacked Draft

- [Issue #215](https://github.com/Dimash313/FileShape/issues/215): `inspect_zip` previously opened user-provided paths through `ZipFile(Path)` without regular-file guard. `unpack_zip` opened the input twice for inspection and extraction, potentially switching inodes between phases. Use the pinned regular ZIP descriptor throughout a single extractor `ZipFile` and reject symlink/FIFO/directory sources without blocking.
- Preserve all existing ZIP bomb/traversal/member-count/byte budgets, CRC rejection, flat indexed filenames, staging cleanup, no-clobber and ArchiveModulePort contracts. Update the existing regular-path-swap test to prove extraction of the originally approved inode instead of merely throwing on a second path open; add seven independent source-type/FD cleanup tests including directory input refusal for the writer. Linux `os.fdopen` rejects directory FD before stream construction, so validate with `fstat` first.
- Stacked Draft on [PR #200](https://github.com/Dimash313/FileShape/pull/200) → #189 → #181 → #168 → #162 → #159 → #153 → #144 → #137 → #128 → #112 → #111 → #109 and architecture parents. Parent #200 exact-head [Actions #43758603926](https://github.com/Dimash313/FileShape/actions/runs/43758603926) passed 691 Python tests, Mini App, Docker; new child needs its own exact-head green CI. No shared API/worker modifications or automatic merges.
