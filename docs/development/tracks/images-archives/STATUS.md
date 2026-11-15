# Images & Archives — handoff

Updated: 2026-11-15 UTC
Track: `images-archives`
Claimed Issue: [#186 — close transient PDF image buffers per page](https://github.com/Dimash313/FileShape/issues/186)
Branch: `fix/image-bundle-eager-buffer-release-h9`
PR: [#189](https://github.com/Dimash313/FileShape/pull/189), **Draft**, base `test/image-concurrent-resources-h8` (PR #181). Inspect live PR for exact final head after docs.

## Proposed changes (Draft, not merged)
- `services/image_bundle.py`: nested short-lived `ExitStack` around each decoded original and temporary RGBA buffer, freeing both before the next image is decoded. Keep outer `ExitStack` for completed RGB PDF page canvases only, so Pillow can safely encode all PDF pages. Register the freshly allocated white RGB canvas for cleanup **before** alpha paste to avoid leaks if paste fails.
- `tests/test_image_bundle_transient_release.py`: 4 tests for immediate source closure before next decode, RGBA closure, paste-error canvas cleanup and preservation of previous target on corrupt later member.
- `docs/benchmarks/IMAGE_RESOURCES.md`: local *manually reconstructed* three-run before/after memory figures and methodology; not an exact PR checkout nor production performance claim.
- No changes to public image module/API, auth, worker scheduling, per-owner quotas, input formats, EXIF, page ordering, source pinning, per-file/bundle pixel limits, target publication or temp stage naming. No extra provider, audio, payments, media assets or images of living beings (AGENTS.md).

## Verification and evidence
- Parent [PR #181](https://github.com/Dimash313/FileShape/pull/181), head `12422e4bca5757ef90e321879a941cdfdebd2d12`, passed actual [Actions run #43734472561](https://github.com/Dimash313/FileShape/actions/runs/43734472561): **678 Python tests** passed; Mini App tests/typecheck/build and Docker succeeded. Real 2-worker tiny-block workload: 54.562 MiB sampled aggregate child RSS, 55.688 MiB summed independent peak RSS. These are tiny 15,232-pixel-per-job fixtures and not a near-cap concurrency result.
- **Current branch exact-head Actions not yet executed/verified.** Tests written on GitHub. A separate local reconstructed-domain smoke check confirmed original close-before-next decode, RGBA close-before-next decode, and canvas close/preservation on injected paste error. This is not full repo CI.
- Local A/B measured with the same reconstructed-domain benchmark harness, three fresh processes per profile, Python 3.13.5 / Pillow 12.3.0 / pypdf 5.9.0, Linux: near-cap 6×1800² total 19.44m pixels median absolute child peak **306.887 → 195.891 MiB (~36.2% lower)**; typical 1.4784m pixels **114.633 → 105.582 MiB (~7.9% lower)**. These are one-color synthetic files, not actual host or production profile. See `docs/benchmarks/IMAGE_RESOURCES.md`.
- Remaining: exact-head full Python suite/Mini App/Docker, auth/owner-bound bot/API regression, representative deployment container memory and 2-/3-worker near-cap measurement, security review and main CI after parent integration. Do not change runtime concurrency allowances based on these experimental figures.

## Integration dependency
Pending branch → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture parents. All are Draft/unmerged at last branch inspection. Never merge out of dependency order or without real final-head checks/review.

## Next step
- Open a Draft PR for #186; verify full exact-head GitHub Actions including new regression cases. Correct any observed test failure without loosening safety.
- After stable green branch CI, coordinate actual worker concurrency / RSS guardrails with API & Security Issue [#177](https://github.com/Dimash313/FileShape/issues/177). HTTP ZIP extraction remains solely a contract proposal in [Issue #132](https://github.com/Dimash313/FileShape/issues/132).
