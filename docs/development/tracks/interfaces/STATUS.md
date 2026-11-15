# Interfaces & UX — handoff

Updated: 2026-11-15 UTC; branch: ux/bot-message-linebreaks
Track: interfaces
Current Issue: #117 — Telegram bot literal newline formatting
Active PR: draft (see branch ux/bot-message-linebreaks); base docs/independent-development-tracks, dependent on #112
Implemented in branch: replaced escaped newline display sequences in main.py Telegram messages and added tests/test_bot_message_linebreaks.py regression checks.
Verified: source inspected through GitHub connector; automated tests, Telegram device checks, Mini App build, Docker and exact-head CI NOT EXECUTED. Do not claim release readiness.
Dependencies/blockers: #101 GitHub Actions runner allocation; #112 track documentation branch not yet merged. Existing UX standard PR #91 must be coordinated before merging overlapping work.
Next unblocked task: inventory Mini App responsive and accessibility issues, create a separate scoped Issue after checking overlap with open PRs.
Risk / cross-track decision needed: main.py is a shared surface; API/security and format tracks must review integration conflicts. No API/auth/processing logic intentionally changed.
