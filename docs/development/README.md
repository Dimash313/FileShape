# FileShape — independent development tracks

**Status:** proposal in a draft PR, not active in main until reviewed and merged.

This directory is the durable handoff point between independent ChatGPT sessions. **GitHub is the source of truth, not chat history.** A new chat reads the repository, open PRs, issues, and CI results before choosing a task. Do not assume any PR is merged, deployed or tested merely because a STATUS file mentions it.

## Start a new development session

1. Read repository-root `AGENTS.md`, `README.md`, `docs/ROADMAP.md`, `docs/MODULAR_ARCHITECTURE.md`, then `docs/development/RULES.md` and `docs/development/INTEGRATION.md`.
2. Select exactly one track from `docs/development/tracks/`; read its `ROADMAP.md` and `STATUS.md`.
3. Query GitHub **live** for the selected track's issues, draft/open PRs, branch heads, dependencies and latest CI. Verify source code and tests; STATUS is a handoff, not proof.
4. Choose the highest-priority **unblocked** task that no other chat is working on. Record a claim in the Issue before editing. If no independent task is available, report the blocker instead of creating speculative work.
5. Work in a new branch, open a draft PR, run the relevant tests where possible, and report accurately which checks executed versus could not run.
6. Update the track's STATUS and roadmap **in the same PR** with the exact PR/Issue links, branch, outstanding risks, verification results and next actionable task. For an unmerged PR, update status on that branch; do not claim main reflects it.
7. The next chat repeats these steps; no persistent session or hidden memory is required.

Track names: `pdf-documents`, `audio-video`, `images-archives`, `api-security`, `interfaces`.

**Owner's current release sequence:** Telegram bot first, architecture designed for website and standalone mobile clients later. The shared API is programmatic, not a requirement for identical visual UIs. No universal IhsanSoft ID; product-specific account boundaries. No new paid providers, billing or integrations without approval.

**Existing blocker:** GitHub Actions issue #101 reports runner jobs failing before steps execute. No stacked draft PR is production-ready until exact-head CI actually runs and passes. Never treat a zero-step failure as a successful test.

See `docs/development/INTEGRATION.md` for shared-file ownership and merge policy.
