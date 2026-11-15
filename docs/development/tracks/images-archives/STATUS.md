# Images & Archives — handoff

Updated: 2026-11-16 UTC
Track: `images-archives`
Current Issue: [#186 — release transient PDF page buffers](https://github.com/Dimash313/FileShape/issues/186)
Branch: `fix/image-bundle-eager-buffer-release-h9`
Draft PR: [#189](https://github.com/Dimash313/FileShape/pull/189), base `test/image-concurrent-resources-h8` ([#181](https://github.com/Dimash313/FileShape/pull/181)). Reconciled with updated parent #181; **inspect actual PR SHA and CI** before review.

## Domain change (Draft; not merged)
- `services/image_bundle.py`: prepare each RGB PDF page in a short-lived nested `ExitStack`; close the decoded source and temporary RGBA copy before the next page, retaining only the final RGB page canvases until PDF encoding. Register white RGB canvas cleanup before alpha paste so injected failures cannot leak page allocations.
- `tests/test_image_bundle_transient_release.py`: four source/RGBA closure and rollback tests.
- `docs/benchmarks/IMAGE_RESOURCES.md`: real **local reconstructed-source** A/B comparison, not production: synthetic 19.44m-pixel near-cap batch median peak child RSS **306.887 → 195.891 MiB**, about 36.2% lower (3 fresh children/profile), and typical batch 114.633 → 105.582 MiB, about 7.9% lower. CPU timings were noisy; no throughput/SLA claim.
- Preserve JPEG/PNG/WebP format allowlist, pinned file handles, 20 MiB input bytes/22m cumulative pixels, original PDF page count/order, EXIF and white alpha flatten, atomic result publication, owner boundaries and all existing output/API contracts. No paid integrations, copyrighted media or living beings in synthetic fixtures.

## Parent concurrency diagnostic preserved
- This branch is synchronized against the newer parent [PR #181](https://github.com/Dimash313/FileShape/pull/181): exact historical head `a11aa3c9898dddcb6513e4f8148c0d29651bbec1`, green [Actions #43751503357](https://github.com/Dimash313/FileShape/actions/runs/43751503357) (Python, Mini App, Docker).
- Keep parent `docs/benchmarks/IMAGE_CONCURRENCY.md` actual lab results: 2 near-cap workers peaked at **592.906–592.969 MiB** sampled children-only RSS, 3 workers at **889.320–889.434 MiB**, from local reconstructed-domain measurements, **not real worker or cgroup total**.
- Keep parent's `tests/test_image_concurrency_benchmark.py` regression for sampled RSS budget failure cleanup and corrected non-strict /proc-vs-rusage peak interpretation; never regress this parent test when integrating.
- Actual worker admission and cgroup hard limits are owned by API/security [Issue #177](https://github.com/Dimash313/FileShape/issues/177). This branch does not modify worker, API, bot, Mini App, payment, quota or pricing contracts.

## Verification / merge gates
- Before the integration reconciliation, [PR #189](https://github.com/Dimash313/FileShape/pull/189) head `d651cd99b975f28443a690d11ac23a0c710a7497` passed [Actions #43737276758](https://github.com/Dimash313/FileShape/actions/runs/43737276758) (real Python/Mini App/Docker). This does **not** certify the new merge-commit head. Execute all exact-head checks again.
- Parent #181 head `a11aa3c...` passed [Actions #43751503357](https://github.com/Dimash313/FileShape/actions/runs/43751503357). Reconcile HEAD and verify green CI on this new branch tree; review after integration.
- [Issue #197](https://github.com/Dimash313/FileShape/issues/197) / dependent [Draft PR #200](https://github.com/Dimash313/FileShape/pull/200) implement separate ZIP input pinning. #200 on the older #189 parent passed **689 Python tests + Mini App + Docker** [Actions #43754536056](https://github.com/Dimash313/FileShape/actions/runs/43754536056); it must inherit this newer #189 merge commit and rerun its own final-head CI.
- After all ancestor review, integrate in dependency order. Do not merge with red/absent CI or call deployment ready without post-merge main tests and representative bot/API integration.

## Stacked Draft dependency chain
[#200](https://github.com/Dimash313/FileShape/pull/200) → [#189](https://github.com/Dimash313/FileShape/pull/189) → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → earlier architecture parents. All are Draft/unmerged; real exact-head CI required for each updated integration branch.
