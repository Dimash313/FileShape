# Non-negotiable engineering rules for every track

1. **Follow `AGENTS.md` first.** Owner's halal/shubuhat restrictions apply across code, product, design, business, assets and dependencies. Do not add doubtful features by default.
2. **Inspect before editing:** current code, open PRs, tests, recent changes and roadmap. Never duplicate a live feature branch or assume another agent's changes have landed.
3. **One bounded task per PR.** Every PR references a GitHub Issue, describes exact behavior, files changed, tests, compatibility, security and dependencies. A batch of unrelated features is not one task.
4. **Isolation:** format-specific logic stays within its domain; shared APIs/contracts require an explicit coordination Issue and review by the `api-security` track. Do not independently rewrite global auth, quotas, worker scheduling, databases or shared interfaces.
5. **Privacy/security:** authenticated per-owner file access, bounded bytes/count/CPU/memory/time, symlink/path traversal protection, temporary-file cleanup, quota correctness, atomic state transitions and failure handling. Tests must include negative/adversarial cases.
6. **No fake evidence:** do not invent CI passes, test runs, percentages, benchmark results, pricing, user numbers or release status. Clearly label tests written but not executed. A draft PR is not a completed milestone.
7. **Verification:** Python tests, Mini App tests/typecheck/build, Docker checks as affected, real file fixtures and regressions. Exact-head green checks and review are required before merging. GitHub Actions issue #101 currently blocks merges.
8. **Compatibility:** avoid breaking API and bot flows; version contracts and migrations. No deleted working feature without explicit review. No unsupported new paid service, dependency or account system.
9. **UX:** premium minimalism, accessible and platform-appropriate interfaces. Programmatic API may be shared, visual UI need not be.
10. **Handoff:** update `STATUS.md` in the same branch/PR. Include Issue, PR, exact head SHA, what changed, what was verified, what is blocked, and next unblocked task. Never edit STATUS solely to claim completion.
11. **Coordination:** if another PR owns the same files or API contract, stop and negotiate an integration order. Never silently overwrite another chat's changes.
12. **Git discipline:** feature branches from a declared base, draft PRs, CI, review and integration. No auto-merging, no force-push to shared branches, no skipping checks.
