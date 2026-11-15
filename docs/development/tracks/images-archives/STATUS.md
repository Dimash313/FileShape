# Images & archives — handoff

Updated: 2026-11-15 UTC.
Track: `images-archives`.

## Integration chain (all Draft / NOT merged)
- [PR #137 — atomic image output integrity](https://github.com/Dimash313/FileShape/pull/137) · branch `fix/image-atomic-output-h2` · base `fix/zip-extraction-failure-cleanup-g1`; Issue [#133](https://github.com/Dimash313/FileShape/issues/133)
- [PR #128 — staged ZIP extraction with no-clobber rollback](https://github.com/Dimash313/FileShape/pull/128) · Issue [#121](https://github.com/Dimash313/FileShape/issues/121)
- [PR #112 — independent tracks handoff](https://github.com/Dimash313/FileShape/pull/112) → [PR #111 — ZIP writer/reader compatibility](https://github.com/Dimash313/FileShape/pull/111) (Issue #110) → [PR #109 — HTTP ZIP create](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture parents.
- Merge only in dependency order, after real **final-head** green CI and review. Do not rebase or independently merge stacked descendants while parents are unverified.

## PR #137 implementation (NOT in main)
- `services/image_tools.py`: private same-directory stage output with `mkstemp`, explicit Pillow encoder format for all supported image/PDF conversions and WebP optimization, `os.replace` publication only on success and guaranteed stage removal. Preserve target bytes if encoder fails; stage file permissions 0600; close transient alpha-conversion image buffer.
- `tests/test_image_atomic_outputs.py`: seven new offline tests for JPEG/PNG/WebP/PDF and optimized WebP, 35m pixel-header rejection, partial save failure, final rename failure, symlink output protection, private permissions, bad source/format.
- Unchanged: image quality presets, 35,000,000-pixel cap, image module/public API signatures, bot/Mini App processing flow, private owner workspace, quota and API contracts.
- No new paid services, new imagery/media assets, audio, advertising or payment paths; AGENTS.md still applies.

## Verification and blockers
- **Executed locally** on a manually mirrored image module, Python 3.13 / Pillow 12.3: actual JPEG, PNG, WebP, PDF and quality-72 optimized WebP outputs, injected partial encoder and failed-rename cleanup, existing result preservation, mode 0600. These probes **passed**, but are NOT exact-head full-repository execution. Committed seven-test suite still requires exact-head run; do not claim those tests were executed unless a run is captured.
- Earlier PR #128: nine previously mirrored ZIP tests passed locally; full exact-head suite unverified.
- Required and **NOT VERIFIED**: full Python suite, Mini App test/typecheck/build, Docker, representative bot/API images and ZIP, actual production-like filesystem, exact-head GitHub Actions. [CI blocker #101](https://github.com/Dimash313/FileShape/issues/101) remains a release gate; no merge on zero-step or absent checks.
- Verify final head SHA from PR #137 live; this STATUS commit updates the branch after the last code commit.
- ZIP HTTP extraction remains unimplemented: multi-result, owner-scoped retrieval requires `api-security` coordination and separate approved contract.

## Next non-overlapping work
- Review existing staged PRs and CI first; after image atomic output, independently consider atomic multi-image PDF batch output in `services/image_bundle.py` (requires a new claimed Issue and separate PR). Keep no-code client expansion and image size increases out of scope until measured resource tests.
