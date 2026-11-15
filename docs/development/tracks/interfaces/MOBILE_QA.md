# FileShape Interfaces — Mini App mobile and keyboard QA

**Scope:** Draft PR [#173](https://github.com/Dimash313/FileShape/pull/173), Issue [#172](https://github.com/Dimash313/FileShape/issues/172).
**Status:** manual verification **NOT EXECUTED**. This is an acceptance checklist, not proof of compatibility.
The batch-reorder focus check K8 is covered by unit and source-level regressions, but still requires real keyboard/TalkBack verification.

## Before testing

1. Use a trusted preview of the **exact PR commit**, not the public app on `main`. Record the preview URL, build commit SHA, browser/Telegram client version, OS, viewport size and tested date. **Do not claim #173 was tested if the running app does not contain its build.**
2. Use harmless sample files (an empty PDF, a valid small PDF, simple geometric JPG/PNG and a plain TXT); do not upload private data or prohibited content to preview environments.
3. For keyboard checks, use desktop Chromium/Firefox/Safari or a connected hardware keyboard. For accessibility checks, use Android TalkBack in Telegram WebView and/or iOS VoiceOver. Do not treat a mouse-only walkthrough as keyboard/AT QA.

## Keyboard and assistive technology

| Case | Action | Pass condition | Result |
| --- | --- | --- | --- |
| K1 | From the document's first focusable element, press Tab | `Перейти к содержимому` appears visibly above the top bar with readable contrast and focus ring | Not run |
| K2 | Press Enter on the skip link | Focus/jump goes to the `main#main-content` landmark; content is not hidden by the sticky header | Not run |
| K3 | Go to `Инструменты` using the bottom navigation | The newly shown `Все инструменты` H1 receives programmatic focus and is announced once | Not run |
| K4 | Repeat for `История`, `Профиль`, `Главная` | Every section's current title is announced, without focus jumping on unrelated updates or initial load | Not run |
| K5 | Navigate via keyboard / TalkBack through the upload controls | Two invisible native file inputs are **not** tab stops or separately announced; visible buttons remain operable | Not run |
| K6 | Open and cancel the native file chooser from the Tools tab | No unwanted file/mode change; the previous batch or file remains visible where appropriate | Not run |
| K7 | Navigate to PDF page selection and notices | All interactive elements expose readable names/selected states, focus is visible, no keyboard trap | Not run |
| K8 | Using a keyboard, select 3 photos and reorder the middle item up/down | The moved photo retains focus on its own control at the new position; at first/last positions focus moves to its enabled opposite-direction control, not to a different photo | Not run |

| K9 | Trigger invalid file selection, an impossible PDF range, and a failed conversion | TalkBack/VoiceOver promptly announces each error as an assertive alert without moving focus; close button works | Not run |
| K10 | Complete a successful operation and then an error, then the reverse order | Success is politely announced, error assertively; neither inherits the previous message's severity | Not run |

## Mobile layout and functionality

| Case | Action | Pass condition | Result |
| --- | --- | --- | --- |
| M1 | Test at viewport widths **320, 360 and 370 CSS px** | No horizontal overflow or clipped heading, controls, or bottom navigation | Not run |
| M2 | Repeat with increased text size / display font scaling | Text remains readable and primary actions accessible (scroll is acceptable; overlap is not) | Not run |
| M3 | Check focused skip-link position with a status bar/notch and bottom navigation | Link does not hide behind Telegram chrome; screen-title focus respects header and safe areas | Not run |
| M4 | Select a valid photo/PDF via native file picker and cancel a replacement selection | Supported file selection works; cancellation preserves the current valid selection | Not run |
| M5 | Select zero-byte or invalid-sized files | UI surfaces an honest error; no processing is started | Not run |
| M6 | Verify upload versus server-waiting status | Only real transmitted bytes show a numeric percentage. Server processing/validation never claims a fabricated percent | Not run |
| M7 | Turn on reduced-motion / high-contrast settings if available | Focus remains perceivable and text legible; nonessential animation is suppressed | Not run |
| M8 | Return to `Главная` from all bottom tabs | No obsolete Scanner or broken tool entry; section changes and files remain coherent | Not run |
| M9 | Test a wide desktop browser viewport (e.g. 1024 CSS px) and forced-colors mode | Focused skip link aligns with the centered 600px Mini App rather than the window edge, stays fully visible, and uses system focus colors | Not run |

## Sign-off evidence and stop conditions

- Record for each attempted case: **Pass / Fail / Blocked**, environment and a short note. A result of “Not run” is not a Pass.
- Any unresolvable keyboard trap, focus transferring to the wrong photo after reorder, hidden focused element, incorrect file preservation, fabricated progress, or horizontal content blocking a primary action is a **release blocker**. File an Issue with repro steps; do not merge a workaround without tests.
- Required automated gate: exact PR head `miniapp` job passes frontend tests, typecheck and build; `tests` job passes Python and Docker; retain GitHub run URL/commit.
- Required integration gate: parent PRs #112 → #118 → #126 → #136 → #145 → #152, conflicting historical #46 reviewed, independent code review, and successful integration in target branch. **Green CI alone is not 10/10 readiness.**

Maintainer notes: the Mini App is Telegram-first. This document does not authorize a standalone website/app rollout or changes to accounts/API/billing.
