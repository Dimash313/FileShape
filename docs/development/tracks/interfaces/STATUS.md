# Interfaces & UX — handoff

Updated: 2026-11-15 UTC
Track: interfaces
Current Issue: [#172](https://github.com/Dimash313/FileShape/issues/172) — keyboard skip link and navigation heading focus in Mini App.
Active PR: [#173](https://github.com/Dimash313/FileShape/pull/173), **Draft**, branch `ux/miniapp-keyboard-navigation`, base `ux/miniapp-transfer-status-a11y`.
Last code commit before this documentation edit: `d16421289e9d263c7cbd74124a7a0bd9a5c0814a`; recheck **exact PR head SHA** after this update.

## Current implementation (PR #173)

- `miniapp/src/App.tsx`: first interactive element is a keyboard "Перейти к содержимому" link; focusable `main#main-content`; a `screenTitleRef` H1 receives focus **only after** switching the in-app section, not on first render; the hidden native file picker inputs are removed from sequential keyboard focus and accessibility tree while remaining invokable by buttons.
- `miniapp/src/styles.css`: high-contrast, focus-revealed skip link; respects top safe area and sticky header when jumping/focusing.
- `miniapp/tests/navigationA11y.test.mjs`: five source-level Node regression tests cover skip link order/target, hidden file inputs, screen-title navigation focus, visual CSS/safe area, and existing `aria-current` semantics.
- No API, auth, worker, queue, files, payments, dependency or branding changes. Black/white design remains unchanged.

## Actual verification, not assumptions

- Direct GitHub source inspection: selected App and stylesheet hooks are present. New test file was created; **new tests and final-head full CI NOT YET VERIFIED** at time this handoff was written.
- Prior Draft PRs [#112](https://github.com/Dimash313/FileShape/pull/112), [#118](https://github.com/Dimash313/FileShape/pull/118), [#126](https://github.com/Dimash313/FileShape/pull/126), [#136](https://github.com/Dimash313/FileShape/pull/136), [#145](https://github.com/Dimash313/FileShape/pull/145), [#152](https://github.com/Dimash313/FileShape/pull/152) each had real **success** in both GitHub Actions jobs (Python/Docker 11 steps, Mini App 9 steps) at their previously validated exact heads on 2026-11-15. This does not prove the new PR #173 is green.
- Actions runner allocation issue [#101](https://github.com/Dimash313/FileShape/issues/101) was closed after the repo became public. Do not treat previous zero-step failures as code failures.
- Manual keyboard and TalkBack/VoiceOver on actual Telegram Android WebView, phone layouts 320/360/370px and increased text size: **NOT EXECUTED**. Static source tests do not replace this QA.

## Dependencies and integration

- Parent order: Draft #173 → #152 → #145 → #136 → #126 → #118 → #112. #112 also depends on an unmerged architectural chain; merge parent-to-child only after separate review and real exact-head checks. No PR in this chain is deployed or merged by this track.
- Older Draft [#46](https://github.com/Dimash313/FileShape/pull/46) remains conflicting with main and contains old Scanner + a different visual theme. #173 selectively ports *only* keyboard skip and section heading focus. Do not merge stale #46 wholesale.
- Shared bot `main.py` in #118 needs API/security integration review. All Mini App code here keeps supported tools and client API unchanged.

Next step: check exact-head GitHub Actions for #173, fix real failing tests if any, then complete keyboard/screen-reader and narrow-screen device QA before requesting final review/integration. Avoid more stacked PRs until parent integration.
