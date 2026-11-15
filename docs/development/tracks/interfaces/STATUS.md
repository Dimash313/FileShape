# Interfaces & UX — current handoff

Updated: 2026-11-15 UTC
Track: `interfaces`
Current issue: [#172](https://github.com/Dimash313/FileShape/issues/172) — keyboard skip link and section-focus semantics in Mini App.
Draft PR: [#173](https://github.com/Dimash313/FileShape/pull/173); branch `ux/miniapp-keyboard-navigation`, base `ux/miniapp-transfer-status-a11y`.

## Implementation

- `miniapp/src/App.tsx`: keyboard skip-to-main link; `main#main-content` and dynamic `h1#screen-title` programmatically focusable. On real section change, an effect focuses the new heading; no focus stealing on initial render or same-tab updates.
- File-picker `input type=file` nodes remain programmatically callable but do not appear in keyboard Tab order/AT tree. Existing valid-file and photo-batch cancellation behavior preserved.
- `miniapp/src/styles.css`: skip link hidden until focus, then clearly visible; fixed above sticky bar, with monochrome contrast, safe-area and scroll margin.
- `miniapp/tests/navigationA11y.test.mjs`: five Node source-level regressions; adjusted input scanning for JSX callback `>` characters after a false-positive local source probe.
- [MOBILE_QA.md](MOBILE_QA.md): acceptance matrix K1–K7 and M1–M8 with explicit unexecuted statuses for keyboard, TalkBack/VoiceOver and 320/360/370 CSS px layouts.
- No API, conversion code, auth, quotas, payments, new tools, branding images, music or new dependencies.

## Verified evidence

- Actual GitHub Actions [run #43731620408](https://github.com/Dimash313/FileShape/actions/runs/43731620408) completed **success** on PR #173 code/test head `2f22fc66ba6d666b54883de29ddd88c06b71dd60`: `miniapp` job **success** (9 steps, including frontend tests/typecheck/build), `tests` job **success** (11 steps, including Python tests and Docker build).
- Subsequent documentation commit(s), including this STATUS update, require a fresh exact-head Actions result. Recheck PR head SHA and final run before merge. **Do not claim final head has passed CI until verified.**
- Real Telegram Android WebView, keyboard, TalkBack/VoiceOver, iOS and increased-text validation: **NOT EXECUTED**. Code/source regressions and CI do not prove accessibility in the device UI.
- Reviewer approvals: none observed for #173 at previous check. This is **Draft**, not release-ready.

## Dependencies, risks, next steps

- Seven open Drafts stacked in order: [#112](https://github.com/Dimash313/FileShape/pull/112) → [#118](https://github.com/Dimash313/FileShape/pull/118) → [#126](https://github.com/Dimash313/FileShape/pull/126) → [#136](https://github.com/Dimash313/FileShape/pull/136) → [#145](https://github.com/Dimash313/FileShape/pull/145) → [#152](https://github.com/Dimash313/FileShape/pull/152) → [#173](https://github.com/Dimash313/FileShape/pull/173). Parent #112 itself depends on unmerged architecture chain. Review owner/cross-track integration before merging, never force merges.
- Old [#46](https://github.com/Dimash313/FileShape/pull/46) is conflicting and includes an obsolete Scanner and different design. #173 selectively ports its skip link and heading focus ideas only; old PR should not be merged whole.
- Actions runner blocker [#101](https://github.com/Dimash313/FileShape/issues/101) was fixed by project owner and is closed; all six preceding Interfaces Draft PR heads had successful Actions as of this checkpoint.
- Next step: exact-final-head CI; manually run `MOBILE_QA.md` with a build of #173; independent review and parent integration. Next unblocked Issue: NONE claimed. Avoid creating further stacked UX PRs before these gates.

## Follow-up keyboard review — 2026-11-15 UTC

- CI checkpoint: [run #43733817332](https://github.com/Dimash313/FileShape/actions/runs/43733817332) completed **success** (9 Mini App and 11 Python/Docker steps) on prior documentation head `a5e4f85a1dc7ba318aea1c0ce86b6300b4798fce`.
- Found a real layout problem in the existing skip-link style: `left:16px` fixed it to the *viewport*, outside the centered 600px Mini App on desktop. Fixed by aligning the focused link to the shell with a 16px minimum margin and viewport width cap. Explicit forced-colors system highlight styling was added to preserve perceivable keyboard focus.
- Added sixth Node regression case and one extra manual QA row, M9; five existing keyboard tests preserved. Direct GitHub CSS/JS inspection passed 7/7 assertions. **Run `npm test`/Actions on this updated final head before declaring CI green.**
- Real keyboard / TalkBack / VoiceOver tests and owner/integrator review remain NOT EXECUTED. No new API, payments, file processing, color assets or dependencies. Keep #173 **Draft**, and do not merge out of its parent branch order.

## Follow-up source review — 2026-11-15 UTC

- GitHub Actions [run #43734804816](https://github.com/Dimash313/FileShape/actions/runs/43734804816) **completed success** at prior head `67dcb3e47758333af4281ddae3a960cc718bc739`: actual Mini App and Python/Docker jobs passed. This evidence applies to that exact commit, not the new batch-focus changes.
- Detected a keyboard accessibility defect in batch photo → PDF ordering: repeated "Переместить выше/ниже" names did not identify the chosen photo; React's `key={index}` retained DOM focus at an old index while photo content swapped. Implemented specific labels including the current photo number and its filename; reorder now restores focus after the DOM update to the same photo's new position. At a boundary, the focus helper selects the *enabled* opposite direction for that photo.
- Added pure `miniapp/src/batchReorderFocus.ts` with guarded index/direction/count and `miniapp/tests/batchReorderFocus.test.mjs` (5 regression cases), plus `miniapp/tsconfig.test.json` inclusion. Direct GitHub inspection matched 8/8 wiring and test configuration invariants; **these are not a substitute for an executed CI run**.
- Updated `docs/development/tracks/interfaces/MOBILE_QA.md` with manual test K8 for keyboard reorder. It is **NOT RUN**. No API, auth, processing algorithm, paid service, image asset, music or other new capability.
- Latest code/test changes require **exact final-head GitHub Actions CI and real keyboard/TalkBack QA** before Draft #173 can be marked ready; upstream stacked parent integration and independent reviews remain outstanding. Recheck head SHA after this STATUS commit.

## Follow-up: accessible failure alerts (Issue #192)

- Issue: [#192](https://github.com/Dimash313/FileShape/issues/192), implemented in existing [Draft #173](https://github.com/Dimash313/FileShape/pull/173) rather than extending the stacked chain.
- Formerly all notices, including invalid file selection, incorrect PDF ranges and request failures, rendered as `role="status"`. App now stores a typed atomic notice object `{ text, kind }` and renders its `role` as `alert` for explicitly identified validation/failure states, or `status` for routine confirmations. Failed job-state messages are alert; other states stay polite. No classification by error wording. Dismissal/navigation clears the notice.
- Added `miniapp/tests/noticeA11y.test.mjs` with 5 regressions, and manual TalkBack/VoiceOver checks K9/K10 (both **NOT RUN**) to `MOBILE_QA.md`. Browser file handling and backend API are unchanged; no new styles/assets/dependencies/payments.
- Direct review checked nine source invariants and explicit alert paths. **This is static inspection, not executed tests.** Fresh exact-head GitHub Actions and real Telegram WebView/AT verification are mandatory. Do not merge while Draft, while any check is pending/failed, or before the stacked parent integration/review.

## PDF page input accessibility correction (2026-11-16)

- Reviewed the current Mini App after #192. Found that PDF page input used `aria-invalid={!validPageSelection}`, which checks range syntax but can report **valid** when the chosen pages violate operation limits (e.g., more than 150 selected or deleting all pages).
- Changed the input to `aria-invalid={Boolean(pageSelectionError)}`, and connected it to the existing `role="alert"` explanation via conditional `aria-describedby="pdf-page-selection-error"`. Existing validation and backend processing unchanged.
- Added one source-level Node regression in `miniapp/tests/noticeA11y.test.mjs` covering the field, descriptive ID and semantic restrictions. Updated manual keyboard QA case K7 to cover syntactically valid but disallowed selections. Tests/QA are **not** automatically evidence of real screen-reader behavior.
- No new PR: this is a correction within Draft #173. Recheck exact-head GitHub Actions, parent stack, independent review and real Telegram/TalkBack QA before merging.

## Release policy and exact-head verification update (2026-11-16)

- Owner no-beta decision in [PR #190](https://github.com/Dimash313/FileShape/pull/190) supersedes earlier statements above that mandated *live Telegram WebView / actual TalkBack testing as a blanket PR merge prerequisite*. There will be no public/closed beta, pilot, early-access or staged user rollout. Internal testing with mocks, fixtures, test doubles, and optional non-public device checks is allowed. Record any unexecuted manual case accurately, and don't declare untested real-device behavior verified.
- [MOBILE_QA.md](MOBILE_QA.md) and [ROADMAP.md](ROADMAP.md) updated accordingly. Known reproducible defects still block release until corrected or the affected capability safely disabled. Parent-stack integration, independent code/security review, exact-head Actions checks and first public release owner approval remain mandatory.
- Python/Docker and Mini App CI passed at **prior** exact head `6db44354c2d2509ba8a644a8496116e8ebbbe955` (run [#43751411108](https://github.com/Dimash313/FileShape/actions/runs/43751411108)).
- One further PDF input accessibility defect fixed: `aria-invalid` now reflects the full `pageSelectionError` (including >150 pages and delete-all), not just range syntax. A conditional `aria-describedby` links the input to its existing inline `role="alert"` explanation; one regression test added. No server validation loosened.
- A GitHub Actions **new final-head** run after this documentation change is required. Until it completes, don't infer success from earlier commits. Draft #173 remains unmerged.

## Integration readiness check — 2026-11-16 UTC

- PR [#173](https://github.com/Dimash313/FileShape/pull/173) previous exact head `267424ed386b0b97921962939ffa76c312ece369` passed full GitHub Actions [run #43754386300](https://github.com/Dimash313/FileShape/actions/runs/43754386300): Mini App and Python/Docker jobs each `success`. All six earlier Interfaces PRs #112/#118/#126/#136/#145/#152 also remain open Drafts with successful final-head CI; no merges occurred.
- New [Issue #201](https://github.com/Dimash313/FileShape/issues/201): history of jobs formerly exposed raw API states (`processing`, `failed`), while the status notification used a duplicate Russian mapping. Within existing Draft #173, imported the API's `JobStatus` type, constrained `Task.jobState` to `JobStatus['state']`, defined one typed Russian label map and reused it in both history and status notification. Alert vs polite role for failed/success remains intact; no fake server state, worker or data model changes.
- A sixth source-level regression was added to `noticeA11y.test.mjs` covering all five API states, type-safety and shared map usage. Corrected an intermediate test-only escaping error before final validation. `MOBILE_QA.md` includes K11, **NOT RUN**, and the K8–K11 table remains contiguous.
- **New exact-head CI must be checked after these code/test/docs commits; earlier success is not proof of the new head.** Independent review is missing. Parent stack and conflicting #46 must be resolved before integration, according to owner no-beta launch policy (no requirement to run a public/closed beta).

## Job history truthfulness fix — Issue #206

- During integration review, found a misleading UI fallback: all history records without a retained Blob rendered an unconditional `<Check/>`, even when the last verified job status was queued, processing, failed or cancelled. This could falsely signal successful completion.
- Fixed within existing [Draft PR #173](https://github.com/Dimash313/FileShape/pull/173): typed `historyStateIcons: Record<JobStatus['state'], LucideIcon>` mirrors the actual API state: queued/processing → Clock3, completed → Check, failed/cancelled → X. A successful local result without a retained Blob still shows Check. Text for every row reflects the typed Russian status or "завершено" for local successful entries. Icons are decorative for screen readers; adjacent text conveys state.
- Added regression test to `miniapp/tests/noticeA11y.test.mjs`, updated previous text-label regression, and expanded optional internal QA case K11. The actual result download action remains available only for retained Blobs; no backend API, job mutation, billing, privacy or worker changes.
- **Latest-code CI not assumed from previous green runs.** Exact final PR head Actions and independent code review still required; Draft #173 remains unmerged. No public or closed beta per owner policy.

## In-memory history ID collision fix — Issue #207

- During audit, found `Task.id = Date.now()` within `remember()`. Two results arriving within the same millisecond could reuse the same React `key`; `checkJob` then updates all rows matching that ID rather than only the target.
- Inside existing [Draft #173](https://github.com/Dimash313/FileShape/pull/173), replaced timestamp-derived IDs with incrementing `nextHistoryIdRef` per Mini App mount. Clearing in-memory history does not reset the ID sequence; no persistence, new service, API change, or additional data retention. The result timestamp text remains a display-only value.
- Added one source-level Node regression in `noticeA11y.test.mjs` and a `MOBILE_QA.md` K12 local/mock test (NOT RUN). The static test checks stable ID assignment, React `key`, and single-record status update selector. It is not a substitute for full simulated integration/CI.
- Exact-head GitHub Actions CI **must run after these commits** and pass Mini App / Python tests / Docker. Independent review, parent-chain integration and owner no-beta release policy still apply.
