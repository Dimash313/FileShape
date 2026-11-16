# FileShape — mandatory instructions for AI coding agents

These instructions apply to **all work in this repository**: code, dependencies, UX, text, marketing, integrations, examples, tests, and future features. Read this file before making changes, and preserve it in subsequent work.

## Public launch and verification strategy

The owner requires **no beta, early access, pilot, or staged user rollout** before the first public release. Follow [docs/NO_BETA_LAUNCH_POLICY.md](docs/NO_BETA_LAUNCH_POLICY.md): build and integrate with full CI, mock-based integration/security/load tests and operational safeguards; do not treat unavailable live-user testing as a blanket PR blocker or falsely claim it ran. Fix reproducible defects before launch. The first user-facing release requires owner approval.

## Project owner's religious and ethical requirements

The project owner follows **Salafi Islam** and requires FileShape to be developed and operated within **halal** boundaries. Do not knowingly introduce haram (religiously prohibited) or doubtful/shubuhat features, content, revenue models, or partnerships. **This is a general, project-wide prohibition: the examples below are NOT an exhaustive list. An unlisted haram or doubtful activity is equally excluded.**

- **No music or musical soundtracks** in the app, bot, previews, promotional materials, or notification sounds. Audio-file tools may process user-provided files as general-purpose utilities; do not supply or promote prohibited content.
- **Do not add depictions of living beings** (people, animals, characters, mascots, illustrations, avatars) to the product branding, generated UI assets, or marketing. Prefer typography, geometric forms, abstract icons, and neutral interface elements.
- **No pornography, erotic material, gambling, betting, lotteries, raffles, interest/riba-based financial products, deceptive advertising, fraud, or other clearly prohibited business models.** Do not build promotional or discovery features for such activities.
- Avoid **religiously dubious content, sponsorships, monetization methods, and third-party services**. Do not assume a technically possible or profitable feature is acceptable.
- No misleading claims, fake reviews, false urgency, fabricated progress, or unverified payment/availability promises. Protect privacy and user trust.
- Keep FileShape a **neutral, useful file utility**. Do not add unsolicited religious preaching or present the application as a source of religious rulings.

## Decision rule for agents

1. Before proposing or implementing a feature, check whether its purpose, UI, assets, dependencies, payment method, or marketing could conflict with these requirements.
2. If something is **clearly prohibited**, do not implement it; propose a permissible alternative.
3. If something is **uncertain or disputed**, **stop and ask the owner for explicit approval** before implementing it. Do not independently issue a fatwa or assert that a disputed question is definitively halal/haram.
4. Respect the owner's final product-scope decision while continuing to follow applicable safety, security, legal, and platform requirements.
5. In each PR description, briefly note whether the change introduces any new content, audio, imagery, advertising, payments, or third-party integrations, and whether owner review is needed.

These rules are **permanent project constraints**, not optional styling preferences. They supplement (and do not replace) the repository's security, testing, and production-quality requirements.

## Prelaunch verification precedence

The owner requires **no beta, pilot or early-access release**. Follow [docs/NO_BETA_LAUNCH_POLICY.md](docs/NO_BETA_LAUNCH_POLICY.md): test aggressively with automation, representative files, simulations and CI. Unperformed live Telegram/Android user tests are recorded as NOT EXECUTED and are not a standalone PR merge blocker. Keep unverified unsafe or payment features disabled; never claim a verified 10/10 or production performance without evidence.

## Mandatory UX policy — button-first, for all FileShape surfaces

The owner requires a **clear, compact, button-first interface** across the
Telegram bot, Telegram Mini App, future web app and native mobile apps.
This is a permanent project-wide product rule for all human and AI contributors,
not an optional preference or a single MP3-editor exception.

1. **Choose actions with visible controls.** Use Telegram inline keyboards,
   menu/back/cancel buttons, or accessible mobile/web buttons and selectors.
   Do not make users memorize commands, type action names, or enter a
   pipe-separated multi-field form just to select what to edit.
2. **Request free text only for actual user content or precision values.**
   Examples: new filename/title/artist/album, year, keyword, page range,
   and exact audio timestamps. Prefer button presets, increment/decrement
   controls, page pickers and timelines where practical; allow manual input
   as a clear fallback for precision. Never replace a necessary input with
   dozens of confusing buttons.
3. **One clear choice at a time.** For an editor, show a compact keyboard
   listing editable fields (e.g. MP3 title, artist, album, year, genre,
   cover), then ask only for the selected value or file. Provide a
   convenient return-to-editor button after a successful change.
4. **Always show escape routes.** Multi-step flows need visible Back and
   Cancel controls, sensible recovery from wrong/expired callbacks, and a
   clear return to the home/tools menu. Text commands such as `/cancel`
   may remain as secondary shortcuts but are not the sole way out.
5. **Honest states and limits.** Never show an enabled action for an
   unsupported operation. If a feature is planned, mark it as
   unavailable/coming soon without pretending that it works. Show real
   progress only; do not fabricate percentages, file previews, prices,
   entitlement or processing status.
6. **Accessible, mobile-first layout.** Keep labels short and readable,
   avoid crowded rows and excessive emojis, prefer 1–2 buttons per row
   in Telegram and tap-friendly targets in mobile UI. Ensure keyboard
   navigation, focus/disabled states, readable contrast and screen-reader
   labels where the platform supports them.
7. **Security and billing are server-side.** Buttons and FSM state are
   presentation, not authorization. Verify owner, file identity, action,
   quota, idempotency and actual capability on the backend. A cancelled
   or invalid selection must not silently charge an operation.
8. **UX regression checks.** For each new feature, test that its action
   is reachable from the relevant menu, unsupported actions are hidden
   or disabled, input is requested only after selection, Back/Cancel
   work, and stale/foreign callbacks cannot execute it. Review the
   experience on a narrow mobile viewport before calling it ready.

**Review gate:** every PR introducing a user-facing flow must explain its
button/navigation path, any unavoidable typed input, and how the user
goes back or cancels. Do not merge new text-heavy wizard flows without
the owner's explicit approval.

## Mandatory product-quality standard — 10/10 target in every dimension

**Owner's non-negotiable ambition:** FileShape must strive for **10/10 quality
in every aspect**, not merely an acceptable average. If any aspect falls
short of the defined release bar, improve it before declaring that release
ready. This applies to the Telegram bot, Mini App, backend, web, Android,
iOS, documentation, support, and every new feature.

**Do not pretend perfection has been proven.** A score of 10/10 is a target,
not a factual certification or substitute for evidence. Never assign
self-congratulatory scores without reproducible tests and independent
user feedback. Record defects, limitations, risks and missing evidence
openly. Zero known release-blocking defects is mandatory; unknown defects
can still exist.

### Mandatory quality dimensions

Evaluate each applicable dimension separately, with evidence and acceptance
criteria in [QUALITY_STANDARD.md](docs/QUALITY_STANDARD.md):

1. Functional correctness and feature completeness within promised scope
2. Button-first UX, visual consistency, mobile responsiveness and accessibility
3. Security, authorization, user isolation and abuse prevention
4. Privacy, data minimization, retention and safe deletion
5. Reliability, crash/restart recovery, idempotency and error handling
6. Performance, resource limits and verified capacity
7. File fidelity, format validation, output quality and metadata integrity
8. Payment/quotas transparency, accounting and refund safety (when enabled)
9. Automated tests, CI, reproducible builds, release/rollback and observability
10. Documentation, maintainability, localization, user trust and support
11. Compliance with the owner's project-wide halal and doubtful-content policy

### Hard release and PR gates

- **No averaging away a failure:** one failing critical dimension blocks
  release, regardless of how strong the other dimensions are.
- Each user-facing PR must document scope, before/after UX, failure paths,
  automated tests, security/privacy impact, resource limits, and remaining
  risks. Provide screenshots or reproducible manual evidence for UI changes
  where possible.
- No merge while required CI is red, skipped unexpectedly, or unrun. Tests
  must cover realistic successful and failed cases; mock-only tests do not
  prove live Telegram, real FFmpeg, payment or production behavior.
- No release with known critical/high severity vulnerabilities, cross-user
  data leaks, silent data loss, false charges, broken core flows, misleading
  functionality, or inaccessible essential actions.
- Treat medium/low defects and enhancements as tracked work with severity,
  owner and decision. Do not claim a dimension is perfect while significant
  gaps remain. For any unmet quality criterion, open or update a task,
  implement the fix, test it, and re-evaluate before claiming readiness.
- New features may remain experimental behind disabled controls or feature
  flags, but must not be advertised as ready or block a stable core release
  merely because they are planned.
- Never trade away security, privacy, truthfulness, religious constraints or
  basic usability to achieve an aesthetic score, performance benchmark or
  release deadline.

**Quality is continuous:** after release, measure real failures and user
experience, fix regressions, and raise the bar. A claimed 10/10 without
evidence is a violation of this standard.

### Per-function and per-line engineering excellence — mandatory

The 10/10 target applies **recursively**: not only to the whole product,
screen, or feature, but to **every function, method, class, module, API,
database migration, configuration change, test, dependency, and line of code
changed**. Review untouched code whenever a change relies on it. Never use
a good overall score to excuse a weak individual component.

For **each implementation**, engineers and AI agents MUST:

1. **Prove necessity and clarity:** choose the simplest maintainable design
   that solves the actual user need. Avoid dead code, duplicated logic,
   magic values, unjustified abstractions, speculative complexity, and
   unnecessary dependencies. Naming, types, contracts and ownership must
   be clear.
2. **Prove correctness:** define inputs, outputs, invariants and failure
   behavior; cover edge cases, invalid inputs, boundaries, encoding, file
   corruption and concurrency where applicable. Never silently swallow
   errors or fabricate results.
3. **Prove security and privacy:** validate at trust boundaries, enforce
   server-side identity and ownership, prevent injection/path traversal,
   protect secrets and user files, bound CPU/memory/disk/time, and delete
   temporary artifacts. Re-check these at the function level.
4. **Prove robustness:** handle timeouts, retries, cancellations, stale
   callbacks, partial failures, crash/restart and idempotency as applicable;
   preserve backwards compatibility or document a deliberate migration.
5. **Prove efficiency:** avoid needless downloads, conversions, memory
   copies, blocking I/O, repeated database queries and unbounded loops;
   measure hot paths before asserting performance improvements.
6. **Prove testability:** add meaningful unit, integration and regression
   tests, including negative cases; verify exact-head CI and simulated runtime
   behavior before first launch; label real-world-only checks NOT EXECUTED until after public release. Tests themselves must be deterministic, readable
   and free of false positives.
7. **Prove usability:** for user-visible changes, ensure discoverable
   button-first interaction, accessibility, consistent visual states and
   honest progress/errors. A working backend with an unusable UI is not
   finished.
8. **Prove maintainability:** keep modules focused, review complexity,
   use consistent style, document non-obvious choices and update accurate
   public docs. Remove obsolete code only with evidence that it is unused.
9. **Prove ethical compliance:** check the permanent halal/shubuhat
   requirements at the smallest change scope, not only at release.
10. **Review every changed line:** no TODO placeholder masquerading as a
    shipped feature, no knowingly broken tests, no unreviewed generated
    code, no copy-paste implementation without understanding and checking
    its dependencies.

**Granular acceptance gate:** each PR must include a change-by-change
quality review: affected functions/modules, risks, tests, residual gaps and
evidence. If any changed component has a known release-blocking defect,
fix it before merge. For lower-severity issues, track them transparently
and do not describe that component as 10/10 until resolved. Do not claim
that every line has been formally proven perfect; document the checks
actually performed and what remains unverified.

### Whole-project excellence and adversarial quality review — ALL surfaces

**Non-negotiable scope:** the 10/10 aspiration and all hard gates apply
to the **entire FileShape system**, including shared libraries, third-party
dependencies, backend, API, worker, storage, queue, databases, infrastructure,
CI/CD, deployment, Telegram bot, Telegram Mini App, public website, web app,
Android and iOS apps, onboarding, navigation, accessibility, localization,
support, pricing, payments, operations, monitoring, and all interactions
between them. A channel, feature, or platform is **not exempt** merely
because it is new, experimental, internal, or developed by a different AI.

**Whole-system rule:** a collection of individually good components is
insufficient. Their integrations, shared data contracts, cross-platform
consistency, state transitions, and failure/recovery behavior must also
meet the same high bar. Review the **entire affected execution path**,
not just changed lines. Keep the full codebase maintainable: proactively
track and reduce technical debt, obsolete paths, inconsistent interfaces,
unnecessary complexity and dependency risks. Do not make cosmetic
improvements while leaving critical system defects unfixed.

**Think like a demanding user, independent reviewer and adversarial
tester.** For every feature and release, actively seek:
- security bypasses, authorization gaps, cross-user leakage, replay,
  forged inputs, payment/quota abuse, unsafe file parsing and exhaustion;
- broken cross-client workflows, inconsistent results, races, stale
  state, partial failures, crashes, restarts and recovery gaps;
- hidden UX dead ends, confusing controls, inaccessible tasks, clipped
  layouts, misleading messages and inconsistent behavior on narrow phones;
- corrupted or degraded output, metadata loss, incorrect file detection,
  undocumented format limits, privacy leaks and retention mistakes;
- maintainability risks, duplicated code, weak contracts, missing tests,
  fragile migrations, unverified deployment claims and ethical-policy gaps.

**No known exploitable loopholes or release-blocking flaws.** Fix and
retest every confirmed critical/high issue before merge or launch.
Record all other findings, prioritize remediation, and do not claim
perfection while material issues are unresolved. Include both
cross-surface integration tests and negative/adversarial test cases
where relevant; periodically commission independent reviews when
feasible. Never interpret “no loopholes” as a promise of absolute
security or zero unknown bugs.

**Applies permanently** to current and future products and platforms,
and to every contributor, automation and AI coding agent. A release
must have evidence-backed PASS for every applicable mandatory gate
across every shipped surface, not a blended average score.
