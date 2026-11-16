# API & security — handoff

Updated: 2026-11-16 UTC; consult current GitHub branches, HEAD SHAs and Actions before treating this snapshot as current.

## Current focused work

- Issue: [#228](https://github.com/Dimash313/FileShape/issues/228) — pinned legacy HTTP download descriptors / no-follow output symlink swap.
- Branch: `api-security/228-pinned-legacy-downloads`, branched from the integrated public `main`. Draft PR to `main` will be opened after committing the code, regression tests and handoff.
- Files owned: `api/server.py`, `tests/test_legacy_download_cleanup.py`, this STATUS. Other department code, worker parsing, Mini App, ad/Stars and identity logic are out of scope.

### Fix

Four legacy HTTP conversion routes currently instantiate `BoundedFileResponse(FileResponse)` from a workspace pathname. The API checks `is_file()`/size first, but Starlette opens the path later when ASGI sends the response; a malicious/replaced worker output symlink could redirect a legacy download despite the safe worker-returned basename guard.

- `BoundedFileResponse` pins one descriptor from the already-open `Workspace._directory_fd` with `O_NOFOLLOW|O_NONBLOCK`, checks regular service-owned inode, link count=1, positive bytes and the existing 45-MiB output cap. It hands Starlette the stable Linux `/proc/self/fd/N` endpoint with pinned `fstat()`, keeping native GET/HEAD/range and Content-Length/Disposition behavior without buffering files in memory. It suppresses ASGI `http.response.pathsend` so no external web-server process re-opens a mutable filename later.
- Response closes the pinned fd before workspace cleanup, even on stalled/disconnected/erroring send. A weak finalizer also releases the fd if a response is abandoned before ASGI dispatch.
- Regression tests: pre-send output symlink/hardlink rejection; replace a target with an outside symlink **after response construction** and assert that original bytes, never external private bytes, are streamed; pathsend extension suppression; normal GET, HEAD and byte-range output; cleanup and descriptor closure. Existing deadline and disconnect tests remain.
- Scope limitation: protects output pathname substitutions and hardlinks in legacy HTTP downloads; this alone is **not** an OS sandbox against malicious parser code or concurrent mutation of an already-open inode. Background ArtifactStore downloads already use a separate fd-pinned lease protocol, unchanged.

### Validation / integration

- Source base: `main` already contains worker output bounds, environment isolation, repeated cancellation reap and safe worker-output basenames — verified by fetching its current `api/worker_runner.py`; original Drafts [#164](https://github.com/Dimash313/FileShape/pull/164), [#170](https://github.com/Dimash313/FileShape/pull/170), [#213](https://github.com/Dimash313/FileShape/pull/213), [#220](https://github.com/Dimash313/FileShape/pull/220) were closed **without direct GitHub merge**, their relevant changes integrated through separate commits. [PR #220 exact-head CI #43931236523](https://github.com/Dimash313/FileShape/actions/runs/43931236523) passed Python, Docker and Mini App.
- **Current issue #228 tests and exact-head CI not yet verified as of this STATUS write.** Run full hosted Python unittest suite, Docker build and Mini App tests/typecheck/build, with security/integration review. Avoid any auto-merge, force-merge, full-production 10/10 claim, beta or deployment.
- Other API/security Drafts #124 (HTTP upload framing), #135 (ZIP extract design only), #142 (artifact identity), #151 (private traces), #156 (admission), #176 (committed-secret preflight), and CI optimization #102 have changed integration status. Verify live PRs and the code **already in main** rather than assuming any Draft is unmerged or absent.
- CI issue [#101](https://github.com/Dimash313/FileShape/issues/101) closed after restoring public hosted runner availability. Do not add paid services or enable budget overages.

No new music, images of living beings, ads, payments, external APIs, religious content or API features. Respect AGENTS.md and all mandatory quality gates.
