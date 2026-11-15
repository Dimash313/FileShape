# FileShape — mandatory instructions for AI coding agents

These instructions apply to **all work in this repository**: code, dependencies, UX, text, marketing, integrations, examples, tests, and future features. Read this file before making changes, and preserve it in subsequent work.

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
