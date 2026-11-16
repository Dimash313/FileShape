# Track: audio & video — roadmap

**Scope:** audio format conversion, metadata, trim, merge, extraction of audio from video, video format handling, validation, FFmpeg worker safety and domain-specific tests. No music/content assets are added; comply with AGENTS.md.

1. Audit current audio tools, modular adapter PRs #94–#95 and any separate trim/tagging drafts. Identify which functions are actually merged.
2. Define independent domain contracts for trimming, tagging, merging and extracting audio from user-supplied video. Coordinate public HTTP actions with API/security; no unsupported action advertising.
3. Add real-file tests: malformed media, container/codecs, metadata safety, duration bounds, worker timeouts, concurrency and cleanup.
4. Implement one safe, reviewed feature per PR; measure CPU/RAM and file size, preserve existing conversions.
5. Prepare web/mobile capability parity without sharing visual UI or adding new providers.

Each milestone needs Issue + acceptance criteria + branch/PR + exact-head CI + STATUS handoff.
