# Interfaces & UX — handoff

Updated: 2026-11-15 UTC
Track: interfaces
Current Issue: [#149](https://github.com/Dimash313/FileShape/issues/149) — accessible and truthful Mini App transfer progress
Active PR: [#152](https://github.com/Dimash313/FileShape/pull/152) (Draft; base `ux/miniapp-touch-targets`)
Branch: `ux/miniapp-transfer-status-a11y`
Last code commit before documentation: `d052b4628ba07c042ee586c1e5216554e048a521`; **recheck final exact head SHA after this STATUS commit**.

Dependencies: Draft [#145](https://github.com/Dimash313/FileShape/pull/145) → [#136](https://github.com/Dimash313/FileShape/pull/136) → [#126](https://github.com/Dimash313/FileShape/pull/126) → [#118](https://github.com/Dimash313/FileShape/pull/118) → [#112](https://github.com/Dimash313/FileShape/pull/112). Older [#46](https://github.com/Dimash313/FileShape/pull/46) edits `miniapp/src/App.tsx`; review conflicts before integration.

Implemented in Draft #152:
- `miniapp/src/transferPresentation.ts` pure function distinguishes actual measured browser upload %, background post-upload admission wait and synchronous post-upload server response wait.
- `miniapp/src/App.tsx` uses this presentation; numbers appear **only** for an integer upload fraction within 0–100, with an accessible progressbar label and value text. Server waiting states show no numeric percent or fictional confirmation.
- `miniapp/tests/transferPresentation.test.mjs` covers 0–100, malformed/non-numeric progress, background validation wording, synchronous processing wording, and source integration/ARIA.
- `miniapp/tsconfig.test.json` includes the helper in Node test compilation.
- No API, auth, quota, backend, payment, new supported media format or additional external service.

Verification:
- Exact-copied isolated helper compiled with `tsc --strict --target ES2022 --module ES2022 --moduleResolution bundler`; 4/4 isolated module tests executed successfully using Node v22. **Not full repo testing**.
- GitHub branch source inspection passed 7 checks: import, callsite, accessible name, valuenow/valuetext binding, old wording removed and TypeScript test inclusion.
- Fifth Node source-integration test is committed but NOT EXECUTED against complete repo.
- Full `npm test`, TypeScript/Vite build, Python/Docker, manual Telegram WebView, keyboard/screen reader and exact-head Actions checks **NOT EXECUTED / NOT VERIFIED**. GitHub Actions #101 zero-step runner blocker persists until proven fixed.
- Real server processing progress is NEVER claimed. The only percent displayed is browser upload bytes measured by XHR.

Next unblocked task: NONE claimed. Candidate: tab heading/focus announcement and responsive keyboard QA, but older #46 already addresses skip-link/heading-focus behavior, so coordinate/review #46 before duplicating it. Prefer stabilizing the stacked PR chain / restoring CI before adding more dependent UX features.
Risk/cross-track coordination: multiple unmerged stacked drafts, #46 App.tsx overlap, #101 runner allocation. No cross-track API decision required for this presentation-only fix.

Integration checkpoint: two-parent merge of Draft #145 incorporated the single-file picker cancellation fix and its regression test into this branch. Exact-head CI and mobile tests remain blocked/unverified under #101; do not merge until real green checks.
