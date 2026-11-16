# Track: interfaces & UX — roadmap

## Current integration direction (2026-11-17)

**Draft [#233](https://github.com/Dimash313/FileShape/pull/233)** carries the Mini App UX and tests directly onto reviewed current `main` in one candidate (Issue [#230](https://github.com/Dimash313/FileShape/issues/230)), because predecessor architecture drafts #94–#112 were closed rather than merged individually. The old seven-deep Interfaces dependency chain listed below is provenance only and MUST NOT be mass-merged. This candidate excludes `main.py` bot messages: resolve that separately with the audio integration owner. Validate actual current-main CI (frontend, Python, Docker), run independent reviews and use no-beta mocked integration tests prior to any owner-authorized public launch. Device/AT QA remains NOT EXECUTED and optional internal verification; do not claim it was tested.

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

- [#131](https://github.com/Dimash313/FileShape/issues/131) / [Draft PR #136](https://github.com/Dimash313/FileShape/pull/136): reject empty and malformed selected files in the Mini App before processing. Stacked on #126.
- [#139](https://github.com/Dimash313/FileShape/issues/139) / [Draft PR #145](https://github.com/Dimash313/FileShape/pull/145): enforce minimum 44px touch targets on small mobile controls, and wrap long notices. Stacked on #136.


- [#149](https://github.com/Dimash313/FileShape/issues/149) / [Draft PR #152](https://github.com/Dimash313/FileShape/pull/152): accessible progressbar for actual XHR upload and honest, nonnumeric server waiting messages. Stacked on #145. API/worker progress is not fabricated.

- [#172](https://github.com/Dimash313/FileShape/issues/172) / [Draft PR #173](https://github.com/Dimash313/FileShape/pull/173): keyboard skip-to-content and focus dynamic H1 after Mini App navigation; isolates useful accessibility from stale PR #46. Stacked on #152. Automated accessibility regressions required; real-device/AT checks remain optional internal verification and currently NOT EXECUTED, not a beta rollout.

**Next priority:** apply the owner's [no-beta policy (PR #190)](https://github.com/Dimash313/FileShape/pull/190): no public or closed beta/pilot/early-access rollout. Before public launch, verify keyboard focus and responsive accessibility through source/unit tests and non-public local/CI browser/Telegram mocks where feasible; list unexecuted actual WebView/TalkBack checks as limitations, not automatic PR blockers. Review conflicting historical #46, integrate stack with independent review and exact-head CI. Do not implement standalone website or Android/iOS clients in this release. #101 was resolved; do not treat old zero-step failures as active.
