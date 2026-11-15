# Interfaces & UX — handoff

Updated: 2026-11-15 UTC; branch: `ux/miniapp-empty-file-preflight`; last code commit: `36197a3ed8dee096366e93f69bbe951d894eec3e` (recheck exact PR HEAD after this documentation commit)
Track: interfaces
Current Issue: [#131](https://github.com/Dimash313/FileShape/issues/131) — empty and malformed Mini App file selection
Active PR: [#136](https://github.com/Dimash313/FileShape/pull/136) (Draft, base `ux/miniapp-tool-pickers`)
Parent stacked PRs: [#126](https://github.com/Dimash313/FileShape/pull/126) → [#118](https://github.com/Dimash313/FileShape/pull/118) → [#112](https://github.com/Dimash313/FileShape/pull/112).

Implemented in Draft PR #136:
- `miniapp/src/filePreflight.ts`: pure preflight validates single-file positive safe-integer size and existing <=20 MiB cap; validates batches of 2–8 supported images with positive sizes and aggregate <=20 MiB.
- `miniapp/src/App.tsx`: uses preflight before selecting a single file or batch, reports distinct empty/oversized/unsupported errors, and leaves an existing valid selection intact after invalid attempts.
- `miniapp/tests/filePreflight.test.mjs`: five regression cases for empty/non-finite/invalid sizes, exact 20 MiB boundary, image types and batch count.
- `miniapp/tsconfig.test.json`: compiles new module into Node test output.
- No API, quota, auth, server format support, payments or third-party dependencies changed.

Verified:
- Source from GitHub connector matched intended imports, single/batch call sites, test TypeScript inclusion and removal of old incomplete checks.
- In a local isolated temporary harness, exact copied source compiled using `tsc --strict --target ES2022 --module ES2022 --moduleResolution bundler --lib ES2022,DOM`.
- `node --test tests/filePreflight.test.mjs` passed **5/5** cases.
- Full repository `npm test`, Vite build/typecheck, Python tests, Docker and mobile Telegram WebView/320 px visual tests **NOT EXECUTED**. Local repository cloning blocked by unavailable GitHub DNS. Never treat isolated tests as full integration proof.
- Exact-head GitHub Actions is pending/failing under [#101](https://github.com/Dimash313/FileShape/issues/101); check latest run and zero-step runner failures before merger.

Dependencies/blockers: #101 Actions runner allocation; #136 is stacked on #126/#118/#112; [#46](https://github.com/Dimash313/FileShape/pull/46) touches App.tsx and requires conflict review. No release or merge readiness claimed.
Next unblocked Issue: NONE claimed. Next candidate: focused 320–370px responsive/keyboard/screen-reader focus audit of Mini App, with a separately claimed Issue and independent PR after checking overlapping files.
Risk / cross-track decision needed: no API change in #136; only browser-side preflight hints. Server remains authoritative for malicious files and unsupported content.
