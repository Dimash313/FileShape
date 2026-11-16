# FileShape — integration and multi-chat coordination

## Authority and source of truth

- GitHub Issues define **what** and acceptance criteria; labels identify the track.
- A track ROADMAP defines **order/dependencies**; STATUS records a **handoff snapshot** and links to actual PRs.
- GitHub PR files, head SHAs, reviews, checks and merged commits determine **what is actually implemented**.
- Root `AGENTS.md`, architecture docs and security policy override a track-specific preference.
- No chat is a permanent owner. Any new chat can resume after inspecting the live repository.

## Suggested issue labels

`track:pdf-documents`, `track:audio-video`, `track:images-archives`, `track:api-security`, `track:interfaces`.
Status labels: `ready`, `claimed`, `blocked`, `review`; do not assume these exist until created. Use Issues and PR descriptions even without labels.

## Claims and file ownership

Before starting, comment on the Issue: **track, task, branch, expected files, dependency PR, acceptance criteria**. If an existing claim or open PR overlaps, coordinate instead of racing. A claim is advisory, not a lock; check again before merging.

- PDF/document domain: PDF and DOCX/TXT modules and their domain tests.
- Audio/video domain: audio/video modules and their domain tests.
- Images/archives domain: image/ZIP modules and their domain tests.
- API/security: HTTP/auth/quota/admission/worker/storage contracts and security tests.
- Interfaces: Telegram UI, Mini App, later web/mobile UI and design-system components.

**Shared surfaces** (`main.py`, `api/server.py`, `api/worker.py`, `api/conversion_catalog.py`, shared manifests, database migrations, global CI, `AGENTS.md`) require an explicit cross-track Issue or an agreed handoff. File ownership is a coordination convention, not a hard security permission. Domain tracks propose contracts; API/security owns shared API implementation; interfaces owns user-facing wiring. Avoid touching the same file concurrently.

## Branches and dependencies

- Prefer independent PRs based on current `main` **only if** the needed contracts are already merged.
- When a task depends on an unmerged PR, explicitly set its base to that PR's head branch, link the parent, and mark it **stacked/draft**. It cannot merge before its parents.
- Avoid creating 100 dependent PRs. Plan 100 Issues, but implement in small independent waves.
- The integration session reviews conflicts, contract versions, regression coverage, security, migration/rollback and release readiness; it does not simply approve everything at the end.
- Never merge a PR with failed, skipped, absent or pre-runner CI. Recheck the **final** head SHA after any rebase or fix.
- Preserve branch protection and require review where available. If GitHub Actions cannot allocate a runner (issue #101), do not claim green tests or release readiness.

## Handoff template for STATUS.md

```md
Updated: YYYY-MM-DD UTC; branch/commit: <branch>/<sha>
Track: <name>
Current Issue: #...
Active PR: #... (draft; base <branch>)
Implemented in PR: <specific code and tests>
Verified: <exact commands/runs and results; or NOT EXECUTED>
Dependencies/blockers: <issues/PRs>
Next unblocked Issue: #... or NONE
Risk / cross-track decision needed: <...>
```

A STATUS file may lag behind the repository. Every new chat MUST revalidate it using live GitHub state.
