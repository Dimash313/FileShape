# FileShape — button-first UX audit and checklist

**Policy source:** [AGENTS.md](../AGENTS.md). Applies to the bot, Mini App,
future website, Android and iOS. This audit describes the **current merged
main** and distinguishes it from unmerged experimental PRs.

## Current audit (2026-11-15)

| Surface | Existing button navigation | UX gap / action |
| --- | --- | --- |
| Bot `/start` and `/menu` | Home, tools, profile, plans and help via inline keyboard | Keep labels compact; always show return to home/tools |
| Bot file upload | Category-specific inline action keyboard | Preserve action-first workflow and owner-bound callback checks |
| Bot PDF extraction/removal | Action is a button, page ranges are typed | Add page-choice presets and back/cancel buttons; typed ranges remain for precision |
| Bot PDF merge and ZIP bundle | Inline Done/Cancel during file collection | Add clearer Back and remove-last-file options when safely possible |
| Bot audio conversion/info | Actions are buttons | Keep format choices discoverable; do not advertise unsupported formats |
| Bot audio trim | **Unmerged PR #89** adds button to start, then requires timestamps | Propose duration presets plus optional exact time input, Back and Cancel |
| Bot MP3 metadata | **Unmerged PR #90** replaces a five-field text form with field-choice buttons | Cover replacement is **not yet implemented**; avoid a misleading enabled control, and provide editor return after each successful change |
| Telegram Mini App | Bottom tabs, file cards, tool/action buttons | Audit all screens on narrow devices; prefer selectors to typed action names, explicit disabled states, clear recovery |
| Web/Android/iOS | Not a confirmed released surface | Apply same policy from first screen; do not claim parity or production availability |

## UX acceptance checklist for every new PR

- [ ] Feature is reachable through an obvious button or selector
- [ ] The next screen asks only for the chosen field/file/value
- [ ] Every multi-step flow has Back/Cancel, plus Home where appropriate
- [ ] Invalid or stale actions show a helpful message without consuming quota
- [ ] Unsupported actions are hidden or visibly disabled, never advertised as ready
- [ ] No fabricated percentages, conversion results, payments or quota counters
- [ ] Buttons fit a narrow mobile screen; labels and focus states are accessible
- [ ] Owner and file authorization, usage accounting and resource limits are enforced server-side
- [ ] Automated tests cover menu reachability, validation, cancel and stale/foreign callbacks
- [ ] PR explains unavoidable typed input and provides manual mobile QA evidence

## Design principle

**Buttons for decisions, text only for content and exact values.**
A keyboard-first interface is not a mandate to eliminate every text field.
For example, a user must still be able to type a precise title, filename,
PDF page range or start/end timestamp if that is the most accurate input.

These notes do not authorize merging currently blocked PRs or bypassing
GitHub Actions. Each implementation requires a separate tested branch and
green CI on its final commit.
