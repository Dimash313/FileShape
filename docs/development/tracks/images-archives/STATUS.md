# Images & Archives — handoff

Updated: 2026-11-16 UTC
Track: `images-archives`
Current Issue: [#197 — pin ZIP creation input descriptors](https://github.com/Dimash313/FileShape/issues/197)
Current branch: `fix/zip-pinned-create-inputs-j1`, base `fix/image-bundle-eager-buffer-release-h9` (parent [Draft PR #189](https://github.com/Dimash313/FileShape/pull/189)).
Active PR: pending creation; inspect live branch/PR for **final exact head** after docs.

## Scope in current Draft (NOT merged)
- `services/archive_tools.py`: `make_zip` now opens up to five regular input sources only once, rejects symbolic links and special files with `O_NOFOLLOW` / `O_NONBLOCK` (where supported) and `fstat`, pins file descriptors for both compressed pass and optional stored fallback, and writes bounded 64-KiB blocks from the already-open streams via `ZipFile.open(..., 'w')`. Rechecks file size, exact read byte count, per-member and aggregate budgets before publishing.
- Preserves original archive naming and duplicate suffixes, mode/mtime metadata, normal deflation, stored fallback for extreme ratios, inspector/extraction rules and private staged atomic result publication. Reader output and public ArchiveModulePort unchanged. Path replacement is fenced, but concurrent *in-place* inode mutation remains a separate workspace-isolation concern.
- `tests/test_zip_pinned_creation.py`: seven adversarial and real-file cases (regular path swaps, high-ratio fallback swap, symlink, FIFO, in-place growth/old target preservation, FD closure and ordinary reader roundtrip). One legacy `test_archive_tools.py` failure injector updated to the streamed ZIP output path; test semantics remain target preservation and temporary cleanup.
- No API, Telegram, Mini App, worker, quotas, billing, paid services or dependencies. Only generated neutral text/binary fixtures; `AGENTS.md` applies.

## Verification and blockers
- Work and regression tests are committed on GitHub; **exact-head GitHub Actions not yet confirmed**. Must pass full Python suite (including archive and extracted-format regressions), Mini App typecheck/test/build, Docker and independent review. No production launch/merge.
- Parent PR #189 on prior head `d651cd99b975f28443a690d11ac23a0c710a7497` had a **successful** real GitHub Actions run #43737276758 (Python/Mini App/Docker), but `mergeable:false` at last inspection. Parent #181 advanced from `12422e4b...` to `a11aa3c...` and both edit STATUS; parent #189 must reconcile its newer base before integration. This child is stacked behind #189, so it inherits that gate. Coordination comment left on PR #189; do not force merge.
- [PR #181](https://github.com/Dimash313/FileShape/pull/181) at `a11aa3c...` passed [Actions #43751503357](https://github.com/Dimash313/FileShape/actions/runs/43751503357): Python/Mini App/Docker success. Existing near-cap memory measurements are diagnostic; shared worker policy still API/security [Issue #177](https://github.com/Dimash313/FileShape/issues/177).
- The prior merged-main CI and genuine bot/API deployed workloads remain unverified. No image-domain output change in this branch.

## Stacked dependency chain
This branch → [PR #189](https://github.com/Dimash313/FileShape/pull/189) → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture ancestors.

## Next actions
- Inspect actual GitHub CI and fix concrete failures in this branch; do not loosen safety tests or claim green from an older SHA.
- Coordinate parent #189 branch reconciliation and integration review before this ZIP PR is mergeable.
- Keep ZIP HTTP extraction as a contract proposal owned by API/security [Issue #132](https://github.com/Dimash313/FileShape/issues/132), [PR #135](https://github.com/Dimash313/FileShape/pull/135). Do not enable it here.
