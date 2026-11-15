# Audio & video — handoff

Updated: 2026-11-15 UTC; branch: `audio-video/115-ffmpeg-regressions` (see latest PR head for SHA).
Track: `audio-video`
Current Issue: [#115](https://github.com/Dimash313/FileShape/issues/115)
Active PR: Draft, stacked on [#112](https://github.com/Dimash313/FileShape/pull/112) / `docs/independent-development-tracks`.
Implemented in branch: `tests/test_audio_safety_regressions.py` adds real generated silent WAV, video-bearing MP4 rejection, corrupt media, target validation, real MP3/OGG/WAV roundtrips, over-duration and FFprobe/FFmpeg timeout regressions.
Verified: tests **NOT EXECUTED** locally or on exact GitHub head. No full Python, Mini App, Docker or real Telegram smoke verification claimed.
Dependencies/blockers: runner allocation issue [#101](https://github.com/Dimash313/FileShape/issues/101); architecture PRs [#94](https://github.com/Dimash313/FileShape/pull/94), [#95](https://github.com/Dimash313/FileShape/pull/95); separate trim/tagging PRs [#89](https://github.com/Dimash313/FileShape/pull/89), [#90](https://github.com/Dimash313/FileShape/pull/90).
Next unblocked Issue: NONE selected. First run exact-head regression suite, reconcile overlapping audio drafts, then create a scoped follow-up.
Risk / cross-track decision: do not change HTTP endpoints, shared worker, quota, Telegram UI or manifest without API/security and interfaces coordination. No new audio content, imagery, advertising, payments, dependencies or third-party integrations. Generated test fixtures are neutral and ephemeral.
