# Audio & video — handoff

Updated: 2026-11-15 UTC; branch: `audio-video/115-ffmpeg-regressions` (see latest PR head for SHA).
Track: `audio-video`
Current Issue: [#115](https://github.com/Dimash313/FileShape/issues/115)
Active PR: Draft, stacked on [#112](https://github.com/Dimash313/FileShape/pull/112) / `docs/independent-development-tracks`.
Implemented in branch: `tests/test_audio_safety_regressions.py` adds real generated silent WAV, video-bearing MP4 rejection, corrupt media, target validation, real MP3/OGG/WAV roundtrips, over-duration and FFprobe/FFmpeg timeout regressions.
Verified: isolated local reproduction from reviewed GitHub audio implementation and regression test: `python -m unittest tests.test_audio_safety_regressions -v` **6/6 passed** (Python 3.13.5, FFmpeg/ffprobe available). This is **not** a checkout/CI run of the exact PR head. GitHub Actions run [43720144330](https://github.com/Dimash313/FileShape/actions/runs/43720144330) failed; exact-head full Python, Mini App, Docker and Telegram integration tests remain **NOT VERIFIED**.
Dependencies/blockers: runner allocation issue [#101](https://github.com/Dimash313/FileShape/issues/101); architecture PRs [#94](https://github.com/Dimash313/FileShape/pull/94), [#95](https://github.com/Dimash313/FileShape/pull/95); separate trim/tagging PRs [#89](https://github.com/Dimash313/FileShape/pull/89), [#90](https://github.com/Dimash313/FileShape/pull/90).
Next planned independent task: isolated bounded audio join domain utility, separate Issue/PR after confirming no open overlap; no bot/API wiring without cross-track agreement.
Risk / cross-track decision: do not change HTTP endpoints, shared worker, quota, Telegram UI or manifest without API/security and interfaces coordination. No new audio content, imagery, advertising, payments, dependencies or third-party integrations. Generated test fixtures are neutral and ephemeral.
