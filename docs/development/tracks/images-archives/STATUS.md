# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Current Issue: [#158 — image source format/frame preflight](https://github.com/Dimash313/FileShape/issues/158)
Branch: `fix/image-input-format-preflight-h5`
Active PR: [#159](https://github.com/Dimash313/FileShape/pull/159) (**Draft**, base `fix/image-bundle-predecode-limits-h4`)
Implementation/test commit before docs update: `fcc0e5fb900a27ba4f27f427a9aaae0106a52b57`; see live PR #159 for **final** head SHA.

## Proposed changes in Draft PR #159 (NOT merged)
- `services/image_tools.py`: `_validate_image_input_header` refuses input whose actual Pillow format is not JPEG, PNG or WEBP, or whose `n_frames != 1`. Check before any EXIF operation or pixel decode; independently of filename extension.
- `services/image_bundle.py`: run the same validator in the existing batch-wide header preflight before any image decoding, including for later members.
- `tests/test_image_input_preflight.py`: seven real-file regression tests for supported formats, supported bytes with mismatched suffix, disguised GIF/TIFF, animated WebP/APNG, batch preflight and failure cleanup.
- No shared API/auth/quota/worker/Telegram/UI changes. Existing pixel/file budgets, image quality, PDF page order/EXIF/alpha behavior, atomic output publication and temporary cleanup retained.
- AGENTS.md respected: only neutral solid-color test fixtures, no depictions of living beings, audio/music, advertising, payments, new third-party integrations or media assets.

## Verified / unverified
- **Executed locally** (2026-11-15): Python 3.13.5, Pillow 12.3.0, pypdf 5.9.0 on manually reconstructed domain sources and a lightweight compatibility adapter (not full GitHub checkout). Command `python -m unittest -v tests.test_image_input_preflight tests.test_image_bundle tests.test_image_bundle_atomic tests.test_image_bundle_preflight`: **29/29 passed** (7 new + 22 existing, 0.536s) after adding the 9 existing image-bundle atomic-output tests and using the actual typed `ImageModulePort` source in the local mirror.
- **NOT EXECUTED / NOT VERIFIED**: exact-head complete Python suite with real full module adapter, Mini App tests/typecheck/build, Docker, live Telegram/API end-to-end, benchmark CPU/RAM, GitHub Actions runner jobs. [CI issue #101](https://github.com/Dimash313/FileShape/issues/101) remains blocking. Empty statuses / 0-step jobs are not proof of a pass.
- Before merge: verify PR #159 head, changed-file scope, review, actual final-head green CI; after parent integration verify main CI and deployment filesystem.

## Stacked Draft dependencies (all unmerged at this snapshot)
- [#159](https://github.com/Dimash313/FileShape/pull/159) (Issue #158) → [#153](https://github.com/Dimash313/FileShape/pull/153) (Issue #148) → [#144](https://github.com/Dimash313/FileShape/pull/144) (Issue #138) → [#137](https://github.com/Dimash313/FileShape/pull/137) (Issue #133).
- [#128](https://github.com/Dimash313/FileShape/pull/128) (Issue #121) → [#112](https://github.com/Dimash313/FileShape/pull/112) (GitHub-first handoff) → [#111](https://github.com/Dimash313/FileShape/pull/111) (Issue #110) → [#109](https://github.com/Dimash313/FileShape/pull/109) → other unmerged architecture PRs.
- Do **not** merge out of dependency order, skip failed/absent CI, or claim any of these deployed.

## Remaining risks / next actionable work
- A regular input path can still be replaced between metadata/header check and the decoder open; this is out of scope for #159 and may merit a dedicated TOCTOU issue with `api-security` review if input paths become non-private or attacker writable.
- Real peak-RSS/CPU measurements under worker constraints are not established. Do not increase file/pixel limits without evidence. Next task: review and integrate current chain first; any new security fix must claim a distinct Issue.
- HTTP ZIP extraction remains **contract proposal only**, API/security-owned Issue [#132](https://github.com/Dimash313/FileShape/issues/132) / PR [#135](https://github.com/Dimash313/FileShape/pull/135); no runtime enablement in this track.
