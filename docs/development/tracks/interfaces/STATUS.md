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
