# Images & Archives — handoff

Updated: 2026-11-16 UTC
Track: `images-archives`
Current Issue: [#197 — pin ZIP creation input descriptors](https://github.com/Dimash313/FileShape/issues/197)
Current branch: `fix/zip-pinned-create-inputs-j1`, base `fix/image-bundle-eager-buffer-release-h9` (parent [Draft PR #189](https://github.com/Dimash313/FileShape/pull/189)).
Active PR: [#200](https://github.com/Dimash313/FileShape/pull/200), **Draft** on #189. Git data integration of parent #189 + #181 requires a new exact-head CI.

## Scope in current Draft (NOT merged)
- `services/archive_tools.py`: `make_zip` now opens up to five regular input sources only once, rejects symbolic links and special files with `O_NOFOLLOW` / `O_NONBLOCK` (where supported) and `fstat`, pins file descriptors for both compressed pass and optional stored fallback, and writes bounded 64-KiB blocks from the already-open streams via `ZipFile.open(..., 'w')`. Rechecks opened inode/device identity, size, nanosecond mtime, exact read byte count, per-member and aggregate budgets before publishing. The check intentionally does **not** use ctime: Linux renames change ctime without changing pinned contents. This detects ordinary same-size in-place edits, but is not a cryptographic snapshot against hostile writers.
- Preserves original archive naming and duplicate suffixes, mode/mtime metadata, normal deflation, stored fallback for extreme ratios, inspector/extraction rules and private staged atomic result publication. Reader output and public ArchiveModulePort unchanged. Path replacement is fenced, but concurrent *in-place* inode mutation remains a separate workspace-isolation concern.
- `tests/test_zip_pinned_creation.py`: nine adversarial and real-file cases (regular path swaps, high-ratio fallback swap, symlink, FIFO, in-place growth, same-length content mutation in both DEFLATE/STORED passes, old target preservation, FD closure and ordinary reader roundtrip). One legacy `test_archive_tools.py` failure injector updated to the streamed ZIP output path; test semantics remain target preservation and temporary cleanup.
- No API, Telegram, Mini App, worker, quotas, billing, paid services or dependencies. Only generated neutral text/binary fixtures; `AGENTS.md` applies.

## Verification and blockers
- **Previous** ZIP branch head `39126ec2bc4df12da19a26bf5f2f2d19bfaebd4d` passed [Actions #43754536056](https://github.com/Dimash313/FileShape/actions/runs/43754536056): **689 Python tests**, Mini App tests/typecheck/build, Docker all **success**. The seven ZIP adversarial regressions and existing round-trip tests passed.
- Parent [PR #189](https://github.com/Dimash313/FileShape/pull/189) has been reconciled with the newer #181 by a true two-parent Git merge commit `b1fb0f3e1ff7a73e26abbbb49dda52e9d6508f7f`. It preserves #189's early PDF buffer release, #181's measured RSS document and regression tests, and a combined handoff. The parent's **new exact-head CI passed**, [Actions #43757191378](https://github.com/Dimash313/FileShape/actions/runs/43757191378); old [Actions #43737276758](https://github.com/Dimash313/FileShape/actions/runs/43737276758) was green only on prior head `d651cd9...`.
- This ZIP branch **already inherited** reconciled parent #189 in a true merge commit `59cf9011bec252f9903755703fa23c358eb0e8d3` and retains its concurrency evidence, tests and image buffer cleanup. The earlier ZIP CI `#43754536056` was green only on previous head; since then, same-size inode mutation checks and two tests have been committed. The first new 691-test run #43758019520 **failed two existing path-replacement regressions** because the initial metadata guard compared ctime, which changes when a pinned inode is renamed. The new code removes ctime from the guard, retains mtime/size/inode checks and keeps both path-replacement tests. **A fresh exact-head CI must pass** before review/integration. No forced merges.
- [PR #181](https://github.com/Dimash313/FileShape/pull/181) at `a11aa3c...` passed [Actions #43751503357](https://github.com/Dimash313/FileShape/actions/runs/43751503357). Its near-cap resource figures are exploratory, not a production memory limit. API & Security owns real worker policy [Issue #177](https://github.com/Dimash313/FileShape/issues/177).
- Runtime bot/API integration, production deployment, main CI and chain integration remain unverified. Public API, ZIP limits, worker queue, pricing and auth are unchanged in this ZIP PR.


## Stacked dependency chain
This branch → [PR #189](https://github.com/Dimash313/FileShape/pull/189) → [#181](https://github.com/Dimash313/FileShape/pull/181) → [#168](https://github.com/Dimash313/FileShape/pull/168) → [#162](https://github.com/Dimash313/FileShape/pull/162) → [#159](https://github.com/Dimash313/FileShape/pull/159) → [#153](https://github.com/Dimash313/FileShape/pull/153) → [#144](https://github.com/Dimash313/FileShape/pull/144) → [#137](https://github.com/Dimash313/FileShape/pull/137) → [#128](https://github.com/Dimash313/FileShape/pull/128) → [#112](https://github.com/Dimash313/FileShape/pull/112) → [#111](https://github.com/Dimash313/FileShape/pull/111) → [#109](https://github.com/Dimash313/FileShape/pull/109) → architecture ancestors.

## Next actions
- Inspect actual GitHub CI and fix concrete failures in this branch; do not loosen safety tests or claim green from an older SHA.
- Verify the exact new merge head of #200 with GitHub Actions, review its incremental ZIP code only, and integrate parent Draft PRs strictly in dependency order.
- Keep ZIP HTTP extraction as a contract proposal owned by API/security [Issue #132](https://github.com/Dimash313/FileShape/issues/132), [PR #135](https://github.com/Dimash313/FileShape/pull/135). Do not enable it here.
