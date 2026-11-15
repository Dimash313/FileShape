# Track: interfaces & UX — roadmap

**Scope:** Telegram bot menus, Telegram Mini App, later standalone web/Android/iOS visual experiences, accessibility, copy, design system and client-side API integration.

1. Inventory actual bot and Mini App screens/flows, current user-facing errors, loading states and design consistency. Record regressions and accessibility gaps as Issues.
2. Build a reusable **design system**, not one identical visual UI for all platforms. Preserve premium minimalism and AGENTS.md restrictions.
3. Wire each interface to the **real** server capability contract, quotas and readiness. Do not expose unimplemented or unauthorized actions.
4. Improve responsive and accessible controls, file selection, progress backed by real server state, cancellation, retry and user-facing error handling.
5. Plan independent browser, Android and iOS UIs after their identity/session contracts are approved by API/security. Telegram bot remains first release priority.

Each change is a scoped Issue/PR with UI tests, accessibility review, screenshots where appropriate, and STATUS update. Shared API or bot processing code requires coordination.


## Current scoped work (draft; not deployed)

- [#117](https://github.com/Dimash313/FileShape/issues/117) / [Draft PR #118](https://github.com/Dimash313/FileShape/pull/118): correct literal newline sequences in Telegram bot menus and result captions. Stacked on #112.
- [#122](https://github.com/Dimash313/FileShape/issues/122) / [Draft PR #126](https://github.com/Dimash313/FileShape/pull/126): category-specific native Mini App file pickers, supported DOCX/TXT tool entry and removal of the nonworking Scanner. Stacked on #118. The browser file picker is only a hint; API remains the format/security authority.

**Next candidate:** audit 320–370 px Telegram WebView layout, keyboard/screen-reader focus and file/error recovery (including zero-byte selections) in a new independent Issue after checking PR #46 and the current branch. Do not implement a website or standalone Android/iOS UI in this release. #101 remains a CI execution blocker; a Draft PR or tests written are not evidence of deployment.
