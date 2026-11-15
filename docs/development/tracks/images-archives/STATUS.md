# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Current Issue: [#148 — predecode image PDF bundle limits](https://github.com/Dimash313/FileShape/issues/148)
Branch: `fix/image-bundle-predecode-limits-h4`
Active PR: [#153](https://github.com/Dimash313/FileShape/pull/153) (**Draft**, base `fix/image-bundle-atomic-output-h3`)
Implementation/test commit before docs update: `3488a324ad40fc92e947a190db4db4529fd74c97`; **inspect PR #153 live for the final head SHA** because status/roadmap commits follow.

## Scope implemented in Draft PR #153 (NOT merged)
- `services/image_bundle.py`: input file-count and byte checks before any image decoder, reject symlink and non-regular paths including FIFOs. Open all image headers without fully decoding to enforce existing per-image 35m and total 22m pixel caps; warn-to-error on Pillow decompression bombs. Recheck source type, byte budget and actual pixel dimensions during decoding before RGB/alpha page materialization.
- `tests/test_image_bundle_preflight.py`: 10 tests for valid ordered PDFs, early first/later/per-image pixel rejection (no decoder called), source-byte refusal before parsing, symlink/FIFO refusal, corrupt later header, changed decoded dimensions and target preservation on preflight failure.
- Prior image-bundle atomic publication from PR #144 and existing 2–8 count, 20 MiB aggregate bytes, 22m total pixels, 35m per image, EXIF/alpha behavior, page order, result naming and API/bot boundary unchanged.
- No new content/media assets, audio/music, external services, payments, integrations, or UI. AGENTS.md still applies.

## Verification
- **Executed locally** in Linux with Python 3.13.5, Pillow 12.3.0 and pypdf 5.9.0, using manually reconstructed copies of the changed domain modules/new tests plus the existing image-bundle tests. This is **not** an exact GitHub repository checkout.
- Command: `python -m unittest -v tests.test_image_bundle tests.test_image_bundle_preflight` → **13/13 passed** (3 existing + 10 new, 0.450s).
- **NOT EXECUTED / NOT VERIFIED**: full exact-head Python suite, Mini App tests/typecheck/build, Docker, bot/API image workload smoke, peak RSS/CPU benchmarks, branch CI and final-head GitHub Actions. These checks are required, and GitHub runner issue [#101](https://github.com/Dimash313/FileShape/issues/101) is still a release blocker. A status-less or zero-step run is not success.

## Dependencies (all unmerged Draft)
- [PR #153](https://github.com/Dimash313/FileShape/pull/153) (Issue #148) → [PR #144](https://github.com/Dimash313/FileShape/pull/144) (Issue #138) → [PR #137](https://github.com/Dimash313/FileShape/pull/137) (Issue #133).
- [PR #128](https://github.com/Dimash313/FileShape/pull/128) (Issue #121) → [PR #112](https://github.com/Dimash313/FileShape/pull/112) (development tracks) → [PR #111](https://github.com/Dimash313/FileShape/pull/111) (Issue #110) → [PR #109](https://github.com/Dimash313/FileShape/pull/109), preceded by unmerged architecture parents.
- Never merge out of sequence or without real exact-head CI, domain/integration review and post-merge main CI.

## Next actionable work
- Before further feature PRs, review #153/#144/#137/#128 for unexpected source changes; measure high-pixel real-input resource use in a bounded worker and reconcile limits with API/security if needed. No increase to upload limits without evidence.
- Owner-scoped HTTP ZIP extraction remains **unimplemented**; contract discussion belongs to API/security, Issue [#132](https://github.com/Dimash313/FileShape/issues/132) / PR [#135](https://github.com/Dimash313/FileShape/pull/135).
- Next unblocked issue: **NONE currently claimed**. New image/ZIP changes need independent Issue + claim, distinct files or an explicit stacked dependency.
