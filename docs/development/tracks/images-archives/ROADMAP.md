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
