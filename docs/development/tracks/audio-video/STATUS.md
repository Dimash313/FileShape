# Audio & video — current handoff

Updated: 2026-11-15 UTC; track: `audio-video`; status on branch `audio-video/123-ordered-join` (PR #127).
All PRs below are still Draft and unmerged. Source of truth: GitHub exact-head runs and code.

## Open work and integration order

- [#89](https://github.com/Dimash313/FileShape/pull/89): Telegram audio trim, base `main`; existing draft, independently owned.
- [#143](https://github.com/Dimash313/FileShape/pull/143): Issue [#134](https://github.com/Dimash313/FileShape/issues/134), FFprobe/FFmpeg input header and demuxer validation, open inode pinning; **stacked on #89**.
- [#167](https://github.com/Dimash313/FileShape/pull/167): Issue [#165](https://github.com/Dimash313/FileShape/issues/165), domain-only audio trim shares the validated open input descriptor across probe/FFmpeg and installs output via atomic no-clobber scratch; **stacked on #143**. No user-facing handler/API/quota edits.
- [#112](https://github.com/Dimash313/FileShape/pull/112) track docs → [#116](https://github.com/Dimash313/FileShape/pull/116), Issue [#115](https://github.com/Dimash313/FileShape/issues/115), generated real-media FFmpeg regressions → [#127](https://github.com/Dimash313/FileShape/pull/127), Issue [#123](https://github.com/Dimash313/FileShape/issues/123), domain-only ordered 2–5-input MP3 join with total duration/size/time limits, private scratch, atomic no-clobber install.
- Independent architecture/audio adapter drafts [#94](https://github.com/Dimash313/FileShape/pull/94) and [#95](https://github.com/Dimash313/FileShape/pull/95); metadata draft [#90](https://github.com/Dimash313/FileShape/pull/90). These must be reconciled by owning tracks before user-facing activation.

## Verified GitHub Actions recovery

Issue [#101](https://github.com/Dimash313/FileShape/issues/101) is **closed**; repository is now public. On 2026-11-15, failed jobs were rerun on **unchanged exact head commits** and actual runners executed Python tests and Docker build (11 job steps) plus Mini App tests/typecheck/build (9 steps):

- #89 head `393f09615b929a5c79251bdb654edb5f6ff3d7b4`: [run 43693945852 attempt 2](https://github.com/Dimash313/FileShape/actions/runs/43693945852) — **both jobs success**.
- #116 head `94adc3ad90095cbfbb1acba3312b99b8becfd14f`: [run 43725066219 attempt 2](https://github.com/Dimash313/FileShape/actions/runs/43725066219) — **both jobs success**.
- #143 head `111e913e1cd2ac0ff02c219065e64ab55a8aec77`: [run 43725192547 attempt 2](https://github.com/Dimash313/FileShape/actions/runs/43725192547) — **both jobs success**.
- #127 previous head `095c3c8789ab07190469b1087c960cadce93016e`: [run 43725350075 attempt 2](https://github.com/Dimash313/FileShape/actions/runs/43725350075) — **both jobs success**. This STATUS edit creates a **new head requiring a fresh exact-head check**.
- #167 head `38ec7204498aaa96312b760a079b81f991eb5990`: [run 43729820079](https://github.com/Dimash313/FileShape/actions/runs/43729820079) — **pending at this handoff**; Mini App job passed, Python/Docker job in progress.

Also ran isolated generated real-silence audio-only tests with SHA-matched files from separate unmerged branches; previous evidence 26/26 on mixed-branch copies. These are not a replacement for integrated CI. The exact PR-head green runs above supersede older zero-step failures but do not mean independent PR stacks are all integrated into one tested main.

## Remaining security and release gates

- Keep all drafts unmerged until parents are integrated in order, conflict review and full exact-final-head CI are complete. No force merge on failed, pending or skipped checks.
- #127 join currently relies on the older unpinned audio helper in its own stack; **do not expose the join to users** until the #143 source-inode fix and new #167 trim safety have been reconciled with this stack or an equivalent protected contract. Size quotas, private workspace and owner-bound input validation remain the transport's responsibility.
- Review metadata and Telegram adapter PRs for compatibility; coordinate any new multi-file API contract with `api-security` and `interfaces`.
- Do not add bundled recordings/music, living-being imagery, forbidden business/payments, or other restricted content; AGENTS.md remains mandatory.

Next action: review exact-head #167 CI and any failures; reconcile #89→#143→#167 and #112→#116→#127 with architecture/metadata drafts before release. Production readiness and 10/10 remain **unverified** pending integrated tests and review.
