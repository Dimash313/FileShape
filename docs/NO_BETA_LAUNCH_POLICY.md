# FileShape — no-beta public launch policy

**Owner decision (2026-11-16): FileShape will not have a public or closed beta, early-access release, pilot launch, or staged user rollout before its first public launch.** The first user-facing release is the public launch of the completed, integrated product. This policy applies to the Telegram bot and its Mini App; future website/mobile launches require separate owner approval.

## Development before public launch

1. **Keep building and integrating.** All five engineering tracks (PDF & Documents; Audio & Video; Images & Archives; API, Security & Infrastructure; Interfaces & UX) may develop in parallel. Do not block implementation or merging merely because live-user or deployed Telegram testing is unavailable before launch.
2. **Require verifiable engineering gates.** Every change must have a scoped branch/PR, dependency and conflict review, final-head GitHub Actions checks, and independent code/security review where applicable. Run Python regression tests, Mini App tests/TypeScript/build, Docker build, and push-triggered main CI after merging. Never merge a red, missing, skipped or pre-runner check. Owner authorization is required for integration and release.
3. **Replace prelaunch user trials with automated and simulated verification.** Use real non-sensitive fixture files, malformed/oversized inputs, format/codec matrices, mock Telegram API/WebApp interactions, integration and contract tests, concurrent users/jobs, replay/restart/failure injection, bounded CPU/RAM/disk/queue tests, cleanup/retention, auth/tenant isolation, and recovery/rollback checks. Exercise full bot → API → worker → result-delivery flows with test doubles where needed.
4. **Make readiness explicit.** Before launch, verify deployment configuration, secret handling, database migration/backup/restore, resource limits, monitoring/alerts, operational recovery, disabled or verified payments, and incident/rollback procedures by automated checks or controlled local/CI simulations as feasible. Do not claim tests or benchmarks that have not actually run.
5. **Fix known defects before release.** Do not defer a reproducible security, correctness, privacy, or data-loss defect by saying "test after launch." When a real-environment behavior cannot be verified prelaunch, record the limitation and provide a safe fallback, conservative limit, or disabled feature until it can be verified.
6. **Launch once, publicly.** No beta cohort or limited-user pilot is a prerequisite or planned release phase. After the owner authorizes the public release, observe actual production behavior, respond to incidents, and improve the product. Postlaunch monitoring is not a substitute for prelaunch automated validation.

## Interpretation of existing documentation

- Any older roadmap, checklist, status note, or PR description that says "beta", "early access", "pilot", "staged rollout" or mandates **real Telegram/Android user testing before the first launch** is superseded **only on that scheduling point** by this owner decision. Such unperformed tests must remain clearly labeled **NOT EXECUTED**.
- Continue prelaunch mock-based end-to-end testing, device-width/accessibility source and build checks, CI, and non-public local verification where feasible. The absence of live Telegram/Android testing is a **known limitation**, not proof of functionality or an automatic PR merge blocker by itself.
- Do **not** waive payment, security, privacy, correctness, resource, migration, or data-loss release gates. If a feature cannot be validated safely enough, keep that specific feature disabled rather than shipping an unsupported claim.
- This policy does not change `AGENTS.md` ethical/halal constraints, user-data protections, GitHub review requirements, or the rule against fabricated progress/results.

**Release sequence:** parallel development → reviewed PR integration → comprehensive automated/simulated release verification → owner-authorized public launch → production monitoring and fixes.
