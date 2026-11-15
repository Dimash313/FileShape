# Images & Archives — handoff

Updated: 2026-11-15 UTC.
Track: `images-archives`.
Active Issue: [#161 — pin input descriptor across image batch preflight/decode](https://github.com/Dimash313/FileShape/issues/161).
Branch: `fix/image-pinned-inputs-h6`.
Draft PR: [#162](https://github.com/Dimash313/FileShape/pull/162), stacked on `fix/image-input-format-preflight-h5` (PR #159).
Initial code/test head before STATUS update: `ee65f5e1b0664752b649d2938273abe6fa2c87c0`. Inspect **live PR #162 head SHA** for exact final commit/status.

## Current implementation (Draft; NOT merged)
- `services/image_tools.py`: context-managed regular-source descriptor with `O_NOFOLLOW` / `O_NONBLOCK` where available and `fstat` regular-file validation. Reject symlink/FIFO input. Extend internal `_open_image` to decode an already-open binary stream without closing caller-owned descriptor; existing Path-based call signature stays compatible.
- `services/image_bundle.py`: pin up to 8 descriptors through whole-batch header preflight and subsequent decode (same inode even if pathname replaced by a different regular file). Rewind stream between phases, use `fstat` for aggregate byte budget and retain pixel/format/frame checks and atomic output.
- `tests/test_image_pinned_inputs.py`: 6 tests for malicious regular-path replacement after approval, original PDF image geometry, header/decoder pinned stream, FIFO/symlink refusal, failure cleanup and Linux file descriptor leakage.
- `tests/test_image_bundle_preflight.py`: one existing mock expectation updated from Path to binary stream, no relaxation of validation.
- No new HTTP endpoints, auth/quotas/worker changes, dependencies, billing, UI or media assets; only generated solid-color test images. AGENTS.md remains applicable.

## Actual verification / blockers
- **Executed locally** on manually reconstructed image-domain modules, not full repo exact head: Linux Python 3.13, Pillow 12.3.0, pypdf 5.9.0; `python -m unittest -v tests.test_image_pinned_inputs tests.test_image_bundle tests.test_image_bundle_atomic tests.test_image_bundle_preflight tests.test_image_input_preflight` → **35/35 passed** (6 new + 29 existing).
- **NOT EXECUTED / NOT VERIFIED**: full exact-head Python suite, bot/API real upload integration, Mini App tests/typecheck/build, Docker, deployed filesystem/Windows behavior, worker peak-memory benchmark, and GitHub CI for this PR. The parent PR #159 GitHub Actions run 43724487247 concluded failure with tests/miniapp jobs failed before steps could be verified.
- Release blocker [#101 — GitHub Actions pre-runner failure](https://github.com/Dimash313/FileShape/issues/101) remains unresolved. Missing commit statuses or zero-step jobs are not passing tests.
- Limitations: `O_NOFOLLOW` is unavailable on some platforms; descriptor pinning protects against path replacement on supporting systems but does not stop mutation *within the same inode*. Private per-owner temp workspace isolation and runtime resource bounds remain required.

## Integration chain
- [#162](https://github.com/Dimash313/FileShape/pull/162) (Issue #161) → [#159](https://github.com/Dimash313/FileShape/pull/159) (Issue #158) → [#153](https://github.com/Dimash313/FileShape/pull/153) (Issue #148) → [#144](https://github.com/Dimash313/FileShape/pull/144) (Issue #138) → [#137](https://github.com/Dimash313/FileShape/pull/137) (Issue #133).
- [#128](https://github.com/Dimash313/FileShape/pull/128) (Issue #121) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) (Issue #110) → [#109](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture parents.
- All are Draft/unmerged at last inspection. Merge in parent order **only after** real exact-head green CI/review; verify main after integration.

## Next work
- First review code and security tests for #162 / #159 and actual head GitHub workflow evidence.
- Independent next task: constrained **peak memory/CPU benchmark** for typical and near-cap solid-color image workloads (measure, do not invent results). No changes to shared API without `api-security` coordination.
- HTTP ZIP extraction is only a proposed owner-scoped contract, API/security Issue [#132](https://github.com/Dimash313/FileShape/issues/132) / Draft PR [#135](https://github.com/Dimash313/FileShape/pull/135); no HTTP extraction execution in this track.
