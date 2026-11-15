# Interfaces & UX — handoff

Updated: 2026-11-15 UTC; branch: `ux/miniapp-tool-pickers`; last code commit: `621da3b4a5e2b7e4808392e59ce46baaa90e0365` (check latest PR HEAD after documentation commits)
Track: interfaces
Current Issue: [#122](https://github.com/Dimash313/FileShape/issues/122) — Mini App category-specific file selection and truthful tool catalog
Active PR: [#126](https://github.com/Dimash313/FileShape/pull/126) (draft; base `ux/bot-message-linebreaks`)
Parent PRs: [#118](https://github.com/Dimash313/FileShape/pull/118) (Telegram bot newline fix) -> [#112](https://github.com/Dimash313/FileShape/pull/112) (track coordination docs)
Implemented in PR:
- `miniapp/src/toolCatalog.ts`: typed catalog exposing only implemented PDF, Photo, Audio, DOCX/TXT, ZIP and batch photo-to-PDF options; native accept hints limited to supported single-file types.
- `miniapp/src/App.tsx`: category-aware picker on both quick tools and Tool list; generic upload resets accept; same-file reselection works; unsupported Scanner removed; existing server/API behaviors preserved.
- `miniapp/tests/toolCatalog.test.mjs` plus TypeScript test config, 3 regression checks.
- Updated this STATUS and track ROADMAP in the same stacked branch.

Verified: live GitHub file inspection; isolated local reconstruction of the tool catalog passed `tsc --strict --target ES2022 --module ES2022 --moduleResolution Bundler` and `node --test` (3/3 passing). **Full repository Mini App npm test/build, Python tests, Docker, 320px/mobile WebView visual checks and exact-head CI NOT EXECUTED.** Isolated results are not proof of full integration.
Dependencies/blockers: #101 GitHub Actions runner allocation (parent #118 had zero-step failed jobs), #112/#118 review and merge order, #46 long-open App.tsx accessibility changes may conflict, #91 UX policy review. This Draft PR is not release-ready.
Next unblocked Issue: NONE claimed. Next candidate is focused Mini App responsive/accessibility and empty-file/error-recovery audit; create new Issue after checking latest PRs.
Risk / cross-track decision needed: `main.py` is a shared surface in PR #118; API/security and format tracks must review the parent. PR #126 changes no API, auth, quota, processing, or new server capabilities. Browser accept filters do not replace server validation.
