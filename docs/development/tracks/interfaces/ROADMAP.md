# Track: interfaces & UX — roadmap

**Scope:** Telegram bot menus, Telegram Mini App, later standalone web/Android/iOS visual experiences, accessibility, copy, design system and client-side API integration.

1. Inventory actual bot and Mini App screens/flows, current user-facing errors, loading states and design consistency. Record regressions and accessibility gaps as Issues.
2. Build a reusable **design system**, not one identical visual UI for all platforms. Preserve premium minimalism and AGENTS.md restrictions.
3. Wire each interface to the **real** server capability contract, quotas and readiness. Do not expose unimplemented or unauthorized actions.
4. Improve responsive and accessible controls, file selection, progress backed by real server state, cancellation, retry and user-facing error handling.
5. Plan independent browser, Android and iOS UIs after their identity/session contracts are approved by API/security. Telegram bot remains first release priority.

Each change is a scoped Issue/PR with UI tests, accessibility review, screenshots where appropriate, and STATUS update. Shared API or bot processing code requires coordination.
