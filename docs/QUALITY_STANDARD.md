# FileShape — 10/10 quality standard and release acceptance

**Status:** mandatory engineering and product target. Read together with
[AGENTS.md](../AGENTS.md), [BUTTON_FIRST_UX.md](BUTTON_FIRST_UX.md) and
[ROADMAP.md](ROADMAP.md).

## Meaning of 10/10

The owner's objective is **10/10 in every dimension**. This is an ambition
that drives continuous improvement, **not** a claim that software can be
mathematically proven flawless. Do not report an unverified 10/10.

Each dimension receives one of: **PASS (evidence linked)**, **FAIL (blocking
gap)**, **NOT TESTED (blocks readiness)**, or **NOT APPLICABLE (reason
recorded)**. A single FAIL or NOT TESTED on a required launch criterion
prevents a production-ready declaration. Record measurements and user
feedback, not just a subjective numeric rating.

## Required acceptance matrix

| Dimension | Release acceptance evidence |
| --- | --- |
| Correctness | End-to-end tests for every advertised tool; invalid files fail safely; no broken critical user journey |
| Button-first UX | Mobile screenshots/recordings at 320/360/390 px; actions discoverable, Back/Cancel/Home, clear disabled states, real user task completion tests |
| Visual quality | Consistent tokens, spacing, typography, dark/light modes, responsive cards, no clipping, no decorative living-being imagery |
| Accessibility | Keyboard/focus support where applicable, semantic labels, adequate contrast, accessible error feedback, touch targets |
| Security | Signed Telegram identity, user isolation, IDOR and replay tests, safe subprocess arguments, dependency/security review |
| Privacy | No unnecessary uploads, bounded temporary retention, verifiable cleanup, safe logs and access control, accurate disclosures |
| Reliability | Crash/restart/retry/cancel tests, durable state, idempotent billing, backup/restore and rollback rehearsal |
| Performance | Measured latency and memory/CPU/disk under representative load, queue and timeout limits, no untested throughput claims |
| File quality | Representative format fixtures, content fidelity/round-trip, metadata preservation, corruption handling and size limits |
| Payments and quotas | Only when enabled: real Telegram test payments, duplicate/refund/reconciliation tests, verified entitlements, transparent pricing |
| Testing and delivery | Python and frontend suites, TypeScript build, Docker build, exact-head CI green, post-merge main CI green, deployment smoke test |
| Documentation and support | Accurate capability matrix, limitations, troubleshooting, clear Russian copy and planned localization, feedback/incident path |
| Ethical constraints | AGENTS.md halal/shubuhat review, no music/depictions of living beings in product assets, no doubtful monetization without owner review |

**User acceptance:** test at least five representative tasks across supported
file types with people unfamiliar with the UI before broad launch. Record
confusion, misclicks and failures; improve and retest. Five is a minimum
qualitative sanity check, not statistical proof of perfection.

## Mandatory code-level quality gate — every function, not only the UI

**Scope:** every changed line, function, class, module, endpoint, database
query/migration, test, build script and configuration file. The whole
product cannot pass by averaging a strong interface against weak code.

For every changed component, reviewers must explicitly check:

- **Purpose and design:** is the code necessary, readable, cohesive, typed
  where appropriate, and free from unnecessary duplication or complexity?
- **Correctness:** are normal, boundary, malformed and unsupported inputs
  handled with clear contracts and accurate output?
- **Safety:** are authorization, user isolation, input validation, path
  safety, subprocess safety, resource caps and temporary cleanup enforced?
- **Reliability:** are exceptions, cancellation, retries, stale state,
  concurrency, idempotency and crash recovery handled where relevant?
- **Performance:** are hot paths bounded and measured when a performance
  claim is made, without needless I/O or memory allocations?
- **Tests:** do meaningful automated tests cover success, failure and
  regressions, with no fake passes or hidden skipped checks?
- **Maintenance:** are names, dependencies, documentation, migrations and
  backwards compatibility reviewed?
- **Product/ethics:** does any visible behavior meet button-first UX and
  permanent halal-only requirements?

**Per-PR evidence table:**

| Changed component | Contract/invariants | Negative and regression tests | Security/performance checks | Status and remaining gaps |
| --- | --- | --- | --- | --- |
| List each affected function/module | Describe verified behavior | Link tests | Link evidence | PASS / FAIL / NOT TESTED |

This is a **review discipline**, not a claim that subjective code quality
or every line can be assigned a scientifically exact score. Missing
verification is NOT TESTED, never automatically PASS. Known blocker/high
issues prevent merging/release; track lesser issues transparently.

## Defect severity and release decisions

- **Blocker/Critical:** data exposure, file corruption/data loss, false
  payment charge, unauthorized operation, core service unavailable, major
  ethical violation. Fix and verify before any production release.
- **High:** broken advertised feature, inaccessible core task, repeated
  crashes, materially misleading status, unbounded resource use. Fix and
  verify before release.
- **Medium:** meaningful friction, incomplete recovery, layout or performance
  problems. Track and resolve before claiming 10/10 for the affected area;
  the owner may explicitly narrow release scope instead of misrepresenting
  unfinished work.
- **Low:** minor polish. Track, prioritize and improve; never silently
  claim an issue-free experience.

## PR review template

Every feature or UX PR should state:

1. **What user problem is solved?** Supported scope and what remains unavailable.
2. **Button flow:** entry point → action → input → result → Back/Cancel.
3. **Failure handling:** invalid, oversized, cancelled, stale and foreign-user requests.
4. **Security/privacy/halal:** new risks, uploaded data retention, content,
   third-party services, audio, imagery, ads and payments.
5. **Evidence:** exact tests, CI run links, screenshot/manual device checks,
   measured resource bounds; clearly identify what was *not* tested.
6. **Quality matrix:** PASS/FAIL/NOT TESTED/N/A for relevant dimensions.
7. **Remaining gaps:** issue references, severity, plan and release impact.

## Target experience: FileShape Studio home

- Brand header with accessible Home/Profile/History actions.
- Prominent **Add file** button; selecting a file shows name, type and
  verified local size without uploading merely for preview.
- Categories: PDF, Images, Audio, Documents, Archives; Video only when
  its actual supported operations are shipped.
- File-aware **action buttons**, never a typed command menu. Keep unsupported
  actions hidden or visibly unavailable.
- Recent jobs only when genuinely retained and accessible; distinguish
  job history from actual stored file bytes.
- Four bottom tabs: Home, Tools, History, Profile; concise labels and
  obvious navigation back.
- Minimal monochrome/graphite base with restrained blue accent; geometric
  icons, consistent spacing, touch-friendly layout, light/dark contrast.
- Real upload progress based on bytes transferred; processing status based
  on server state, never simulated percentages.
- Honest Free/Pro usage and purchases; no Stars checkout until payment
  verification and refund handling pass end-to-end tests.

## Operating procedure

1. Audit and classify gaps against this matrix before scheduling features.
2. Fix the highest-risk failure first; prioritize stability over feature count.
3. Implement in scoped branch/PR, test both happy and failure paths.
4. Do not merge with red/unrun required CI; do not launch with blockers.
5. Reassess every dimension after fixes and user testing.
6. Repeat after production incidents and feedback.

**Success criterion:** demonstrably excellent, reliable and useful software
with no known launch blockers, not an invented numeric perfection score.

## Whole-system, cross-platform and adversarial acceptance

**Coverage:** Telegram bot, Telegram Mini App, public site, web application,
Android, iOS, backend/API, workers, databases, storage, infrastructure,
build/release pipeline, user support and business operations. This standard
is binding for every currently shipped surface and every future surface
when implemented; planned platforms are not falsely marked as tested.

A release review must examine the **end-to-end path**, including all
interfaces and shared dependencies, not just the changed component.

| End-to-end scenario | Required evidence |
| --- | --- |
| Same supported file via bot and Mini App/web/mobile | Consistent output quality, limits, errors and security |
| User identity and ownership | Cannot view, modify or retrieve another user's files/jobs or balances |
| Operation lifecycle | Upload, admission, conversion, cancellation, retry, delivery, cleanup, restart |
| Quota and payments | No bypass through another client; no double charge or unverified entitlement |
| Resource and parser abuse | Bounded large/malformed/compressed inputs, subprocess and disk/memory exhaustion |
| UI across devices | Narrow phones, touch, keyboard, accessibility, light/dark, error and offline states |
| Storage and retention | Expiration, deletion, access revocation and logging consistent across clients |
| Deploy and rollback | Reproducible CI, production-like smoke tests, migrations and safe recovery |
| Ethical compliance | Every channel, dependency, asset, ad and monetization flow follows AGENTS.md |

### Required challenge review

For each major feature or release, assign reviewers to ask:
1. **Where could this fail?** Explore boundary values, unsupported formats,
   corruption, timeouts, retries and interruption.
2. **How could this be misused?** Test permissions, malicious inputs,
   state manipulation, abuse and quota bypass in an authorized test setup.
3. **Where is the experience confusing?** Observe first-time users without
   instructions; measure whether they complete the intended task.
4. **What breaks when platforms interact?** Check consistent API contracts,
   state, output and billing from all shipped entry points.
5. **What has not been tested?** Record it as NOT TESTED, not PASS.

**Release rule:** no critical/high findings, no required untested gates,
no misleading capability claims. Address known weaknesses and re-run
regression and end-to-end checks before release. Absolute perfection is
not provable; a high bar plus continuous challenge testing is mandatory.
