# FileShape

A Telegram file editor and converter by **IhsanSoft**, written in Python with aiogram 3.

## FileShape 4.23 — atomic quota-backed job lifecycle (under development)

**Stage 1 only, not enabled for processing:** `DurableJobStore.create(..., metered=True)`
and `create_idempotent(..., metered=True)` can now reserve allowance and
create a queued job in **one** `BEGIN IMMEDIATE` transaction. When an opted-in
job transitions to completed, failed or cancelled, its accounting decision
commits atomically with the state change. Rejected queued claims, unaccepted
uploads and interrupted jobs after restart release their reservations.
Older, unmetered job records are not retroactively billed. The existing
quota methods retain their public semantics.

**Do not enable purchases or show enforced usage:** bot actions, API legacy
conversions, background submissions, retries and all result delivery/cancel
paths still need an audited end-to-end integration. The existing
`/api/v1/usage` reply must continue to declare `enforced: false` and
`purchases_enabled: false`. This stage has no payment or new paid API.
Regression tests verify atomic admission/settlement, quota races, replay,
tenant isolation and restart refunds. Follow-up 4.23 commits will wire every
entry point and verify entire CI before merge.

## FileShape 4.22 — authenticated usage status (read-only)

`GET /api/v1/usage` exposes the authenticated user's own durable
Free/Pro allowance snapshot and prepaid operation balance using signed
Telegram Mini App launch data. It returns `Cache-Control: no-store`,
`enforced: false`, and `purchases_enabled: false` because the processing
admission paths are **not yet metered** and Stars payments are **not enabled**.
Unavailable storage returns HTTP 503 rather than fabricated counters.
The endpoint accepts no owner ID, payment claims or credit grants from clients.

Next: atomically integrate reservations/settlement across all bot and Mini
App processing paths, and only then enable visible usage meters and checkout.

## FileShape 4.20 — Telegram bot navigation

The bot now provides a navigable welcome message for `/start` and `/menu`, with
buttons for **Studio** (when a valid HTTPS `MINIAPP_URL` is configured),
**Tools**, **Profile**, **Plans**, and **Help**. Tools offer PDF, images,
audio, documents and ZIP categories. Each category explains the available
operations and directs the user to upload a file; the existing file-specific
action buttons remain unchanged. `/help`, `/tools`, `/profile` and
`/plans` also work as commands. Navigation is restricted to the user's
own private chat, and Home clears any unfinished multi-file operation.

**Important:** Free/Pro daily quotas, paid operation packs and Telegram Stars
payments are **not yet implemented**. Profile and Plans explicitly say so,
rather than showing fabricated balances or allowing purchases. The existing
20 MB bot download limit still applies. Next steps: server-side quota ledger,
payment verification and entitlement checks.

## FileShape 4.21 — durable Free/Pro operation ledger (foundation)

This version adds **atomic SQLite primitives** for the agreed starting
allowances: **Free 10 operations per UTC day; Pro 100 operations per UTC day**.
A currently valid server-side Premium entitlement selects the Pro allowance.
Optional operation packs contain **10 or 30 operations**; granted operations
remain in the pack until used and do not expire at UTC midnight.

- `usage_snapshot(owner_id)` returns the actual persisted day, tier, occupied
  daily allowance, remaining daily allowance, pack balance and active Pro expiry.
- `reserve_operation(owner_id, server_generated_key)` atomically reserves the
  daily allowance first, then a pack operation when the daily allowance is used.
- `settle_operation(..., success=True/False)` commits or releases the reservation.
  A failed pack-backed operation returns its pack unit; a failed daily operation
  frees its daily slot. The same settlement may be replayed safely.
- `grant_operation_pack(..., operations=10|30, grant_key=...)` is an **internal,
  trusted-only primitive** with a durable idempotency key. It must only be called
  after future independent payment verification or an authorized grant.
- Cross-connection transactions use `BEGIN IMMEDIATE` and existing private,
  protected SQLite state. Tests cover contention, replay, user isolation,
  UTC day boundaries, restart and conflicting settlement.

**Not yet active for end users:** this is a storage foundation, not a billing
release. Processing endpoints and the Telegram bot **do not yet reserve or
settle operations**. No checkout, Stars invoices, client-side credit grants,
quota enforcement, or live paid limits are enabled by this version. Wire all
processing admissions and terminal outcomes before showing a live usage
counter or enabling paid packs. Existing 20 MB Bot API upload limit remains.

## Implemented (v1.0 foundation — upload validation hardening)

Send a file in a **private chat** with the bot; the bot shows actions appropriate to the file.

**Reusable results**
- Each successfully generated file up to 20 MB includes its own action buttons. You can edit/convert that result again without downloading and re-uploading it.\n- The bot accepts actions on generated files only in the owner's private chat.\n- Outputs larger than 20 MB are sent without action buttons because the standard Telegram Bot API cannot re-download them.\n- Input file cards show filename, type and size.

**PDF**
- Show number of pages.
- Extract the first page or select pages (for example: `1,3-5`).
- Rotate all pages 90 degrees clockwise.
- Remove selected pages (keeps at least one page).
- Combine 2–5 PDFs in the order they are sent (`/done` to finish, `/cancel` to cancel).

**Images**
- Convert JPG, PNG and WebP to JPG/PNG/WebP or to a one-page PDF.
- Optimize to WebP with quality 72 (smaller output is *not* guaranteed).
- Accept images as Telegram photos or as documents; sending as a document preserves original quality.

**Audio**
- Accept MP3, WAV, OGG/OGA, M4A and FLAC as documents or audio; also accept Telegram voice messages.
- Convert to MP3 (128 kbps), OGG/Opus (64 kbps) or WAV (16 kHz mono).
- Show codec and duration. Limit: 10 minutes of audio per operation.
- Requires **FFmpeg and ffprobe** installed on the runtime host; neither is supplied by pip.

**DOCX / TXT**
- Convert DOCX → plain UTF-8 TXT (text and tables only; formatting is not preserved).
- Convert UTF-8 TXT → DOCX (up to 2 MB, up to 5,000 line breaks).
- Show approximate paragraph, table, line and character counts.
- DOCX → PDF is NOT implemented (would require separate rendering software).

**ZIP**
- Inspect ZIP contents and list its first 15 filenames.
- Extract up to 10 safe files from one ZIP (sent as individual Telegram documents).
- Create a ZIP from 2–5 files of any supported or other document format.
- Reject unsafe archive paths, symlinks, encrypted archives and suspicious decompression ratios.

**Limits and privacy**
- Max incoming file size: 20 MB (standard Telegram Bot API download limit).
- Merge limit: 60 MB total, 5 PDFs, 250 total pages.
- ZIP creation: up to 5 files, 60 MB total input; ZIP extraction: up to 10 files, up to 50 MB total expanded size, 20 MB per file.
- Maximum result size: 45 MB.
- Processing concurrency: up to 3 operations.
- Source and result files reside in temporary folders and are deleted after processing.
- The bot has no database or persistent user-file storage.
- The bot uses basic in-process concurrency limits; it needs deployment-level resource limits and isolation before public launch.

## FileShape 4.18 — owner-only advertising dashboard (Mini App)

The Profile tab now loads an advertising desk **only after** the server
confirms owner authorization using Telegram-signed Mini App launch data and
the API's `FILESHAPE_OWNER_ID`. Other users see no advertising controls.
There is no public advertiser UI or alternate client-side owner flag.

The owner can view up to 20 campaigns at once (with bounded pagination);
see exact persisted confirmed-join counts and invite revocation status;
create drafts for an immediate-start campaign that ends after 1–72 hours
or after the chosen verified join goal (whichever condition applies, with
the duration as a safety deadline); ask the Telegram API to create a
separate invitation for each draft; start, pause, resume and stop the
campaign through the existing owner-protected endpoints. Stop requires
a second explicit confirmation. The interface offers copying an issued
invitation, manual refresh, clear failure states and responsive
monochrome styling. The displayed join-goal progress is derived from
`confirmed_joins / target_joins`, never an invented loading percentage.

New `GET /api/v1/owner/campaigns?offset=0&limit=20` returns a stable,
bounded, owner-only SQLite overview with `items` and `total`. Pagination
limits are enforced by both API and store. No raw Telegram member IDs or
pseudonymous member digests leave the ledger. Frontend API replies are
validated and rejected on unexpected counters, campaign IDs or links.

**Before using:** set `FILESHAPE_OWNER_ID` in the API environment, host
the Mini App under HTTPS, and open it inside Telegram as that owner.
Grant the bot `can_invite_users` in each partner channel, and supply its
numeric channel ID (for example `-1001234567890`). A paused campaign does
not revoke the invitation, and joins during the pause are *not* counted.
A terminal campaign can still have a temporarily usable link until Telegram
acknowledges revocation; the owner dashboard displays that status separately.
A real subscription count is not claimed. Other pending work includes a
durable inbound `chat_member` delivery outbox, partner onboarding/consent
flow, and end-to-end Telegram channel testing. No new paid API is required.

## FileShape 4.17 — automatic campaign expiry and Telegram invite revocation

A campaign reaches `completed` when its confirmed-join target is hit or its
scheduled end time passes. The API's existing metadata maintenance loop
now runs campaign expiry every 60 seconds. Campaigns manually `stopped`
by the owner are also terminal.

A terminal campaign with a bot-created invite link **atomically queues** a
Telegram revocation in SQLite. Its pending task survives restarts; migration
backfills older terminal campaigns. The API attempts revocation immediately
after a confirmed join or owner stop, and the maintenance loop retries due
tasks. Telegram must explicitly acknowledge `revoke_chat_invite_link` before
the API records `invite_revocation: "revoked"`. Otherwise the state stays
`pending` and bounded backoff is applied (initially 60 seconds, capped at
one hour). Telegram failures cannot roll back valid join counts or be presented
as successful revocations. No raw member ID, original Telegram error content,
or bot token is written into the revocation queue.

The owner campaign snapshot now includes `invite_revocation`
(`not_applicable`, `not_due`, `pending`, `revoked`),
`revoke_attempts`, and `revoked_at`. This is separate from the
campaign's own `state`; a completed campaign **may still have an
active invitation** until Telegram confirms revocation. Correct operation
requires the bot to retain invitation management rights and the API to have
Telegram network access. If the permission is revoked, retries stay pending
until fixed. The bot cannot retroactively prevent a join between target
completion and link revocation. No durable delivery outbox for incoming
`chat_member` events or advertiser-facing admin UI is included yet.

## FileShape 4.16 — owner campaign management API (CI validation required)

Set `FILESHAPE_OWNER_ID` to the Telegram numeric user ID of the single
FileShape owner in the **API environment**. This must never be supplied by
the Mini App client. Authenticated owner-only routes:

- `POST /api/v1/owner/campaigns/drafts`: create a scheduled duration or
  confirmed-join-target draft (`chat_id`, `mode`, `starts_at`,
  `ends_at`, optional `target_joins`).
- `POST /api/v1/owner/campaigns/{campaign_id}/invite`: request a unique
  Telegram bot-created private invite and bind it to that draft.
- `POST /api/v1/owner/campaigns/{campaign_id}/state`: owner-approved
  `start`, `pause`, `resume` or `stop`.
- `GET /api/v1/owner/campaigns/{campaign_id}`: read the persisted campaign
  status and count of confirmed join events.

Every endpoint requires Telegram Mini App HMAC authentication and the
server-configured owner identity. The bot needs `can_invite_users` admin
permission in each advertiser channel. A Telegram API failure never creates
a fictional link. If binding fails after Telegram creates a link, the API
attempts to revoke it; revocation failures are surfaced as requiring manual
cleanup. The routes expose **no** advertiser access.

**Remaining limitations:** This is an API for an owner UI, not yet a
finished visual admin panel. Campaign expiration and automatic invite-link
revocation are not scheduled, and the join forwarder has no durable outbox.
Counts are verified join events, not live subscriber totals. A deployment
must set `FILESHAPE_OWNER_ID` and configure the bot/API bridge before
these routes can be used. Do not enable public sales before end-to-end
Telegram testing.

## FileShape 4.15 — authenticated Telegram campaign join bridge (CI validation required)

Telegram polling now explicitly requests `chat_member` updates. When Telegram
delivers a **new** human membership carrying a bot-created private invite link,
the bot forwards the channel, exact link, keyed member digest and event time to
the API over `FILESHAPE_CAMPAIGN_JOIN_URL`. The bot signs the entire assertion
with a purpose-separated HMAC derived from `BOT_TOKEN`. The API checks a
30-second signature window, nonce replay, event freshness (5 minutes), and
matches the stored **channel plus invite link** before counting a join in
the existing transactionally deduplicated SQLite campaign ledger.
`compose.yaml` configures the internal URL. No client-facing endpoint
can submit arbitrary membership evidence.

**Operational limitations:** No owner UI currently creates and binds the
campaign invite link; without an owner-approved draft campaign already
configured, the bridge records nothing. Bot must be an administrator with
invite-link rights in each partner channel, and Telegram must deliver
`chat_member` updates. Network failures can lose join events because a
durable delivery outbox is not yet implemented. End-of-campaign link revocation,
reconciliation, and advertiser-facing statistics are not yet wired. The
ledger counts unique *verified join events*, not clicks or guaranteed current
subscribers. Keep the API on the internal network; only one API worker is
supported for the nonce cache and SQLite ownership. Do not claim full
advertising automation until these gaps are closed.

## FileShape 4.14 — Telegram campaign event adapter (CI validation required)

Telegram adapter helpers in `services/campaign_telegram.py` can ask Telegram
to create a distinct bot-owned private invite link for an owner-approved
campaign, revoke that link, and recognize attributable **new** memberships
from actual `chat_member` updates. The adapter rejects promotions, existing
members, missing/unsupported links, bot accounts, and unrelated chats.
Pseudonymous user digests use keyed HMAC, not raw Telegram IDs or unsalted
hashes. Telegram API errors propagate; links and joins are never fabricated.

**Not yet live:** These helpers are not registered with the bot polling
dispatcher or linked to the API-owned SQLite campaign ledger. A future
authenticated internal bridge must verify chat ID and exact invite link
against the stored campaign before recording a join; do not write to SQLite
from the bot process. Likewise, a future owner-only admin flow must invoke
link creation and bind it to a draft campaign, with cleanup if binding fails.
Automatic link revocation on completion and real-time advertiser reporting
remain pending. Bot admin permission `can_invite_users` and subscription
membership-check permissions are required for each partner channel; Telegram
must deliver `chat_member` updates. No subscriber statistics are available
until those integrations are deployed and verified.

## FileShape 4.13 — advertising campaign ledger (CI validation required)

The private API-owned SQLite store now has an **owner-only advertising
campaign ledger** with two explicit completion modes: scheduled duration and
target number of confirmed joins, always bounded by a maximum end time.
Campaigns are created as drafts, receive a unique Telegram private invite
link, and can be started, paused, resumed, stopped or completed. State
transitions and owner changes are audited. Replayed join events for the same
campaign/user are counted once, and different campaigns never share their
counts. Event storage uses keyed user digests rather than raw Telegram IDs.

**Important: storage and lifecycle only.** The Telegram `chat_member`
adapter, bot-generated invite-link creation/revocation, owner admin UI,
background expiry scheduler, and real advertiser analytics are **not wired
yet**. Therefore no production campaign is running, no real joins are being
recorded and no subscriber count is being advertised. The internal
`record_confirmed_join` method must only be called after verifying a real
Telegram join event and matching its exact bot-generated invite link.
Successful membership checks are not join events, and Telegram does not
provide reliable invite-link click counts. Do not accept client-supplied
membership or raw user IDs as trusted event evidence.

## FileShape 4.12 — bot/API access bridge (CI validation required)

Docker Compose now configures the Telegram bot to call the **internal** API endpoint
`http://api:8000/internal/v1/access/check` before any bot-side file operation.
The bot never opens or writes the API's exclusive SQLite job/entitlement database.
Bot and API authenticate each internal request using a short-lived HMAC
assertion derived from the already-configured BOT_TOKEN, the trusted Telegram
sender ID, a timestamp and a random nonce. The API rejects unsigned, expired,
forged and replayed requests. The token itself is never transmitted in the
internal HTTP request, and the response contains only the access decision.

The access check is enforced before single-file actions, PDF page extraction,
PDF merge and ZIP creation, including the completion of multi-step actions.
Foreign-chat callbacks are not accepted; denied operations do not download
files or create new temporary conversion work. Premium bypass and
owner-configured required channels are evaluated by the same API-owned policy
as Mini App processing. Failed API/Telegram checks deny new work rather than
claiming membership. Bot help/start, file menus and existing Mini App result
downloads are unchanged. No change to bot file retention or size limits.

**Deployment:** Compose enables the bridge automatically; the API must be
reachable from the bot service on the trusted Compose network. A standalone
`python main.py` launch continues in its legacy, ungated mode until
`FILESHAPE_ACCESS_GATE_URL` is set to a trusted internal API address; do
not enable mandatory channels on such a deployment. If a configured bridge
is unreachable, the bot **fails closed** and does not perform conversions.
The internal path is deliberately not forwarded by the example public Caddy
proxy, which forwards only `/api/*`. Protect the internal service/network;
the HMAC is an authorization control, not a replacement for network isolation.
Required-channel links and the campaign invite-link/statistics admin module
are not delivered yet. Do not enable a restrictive channel configuration before
users have a legitimate way to discover its invitation link.

## FileShape 4.11 — Mini App admission gate (CI validation required)

The API now checks the signed Telegram user against owner-configured active
required channels **before accepting new processing** on all four routes:
`POST /api/v1/jobs`, `POST /api/v1/jobs/{job_id}/retry`,
`POST /api/v1/convert` and `POST /api/v1/images/pdf`.
Configuration and Premium expiry come from the API-owned private SQLite
metadata store. Active Premium bypasses required channels. Without active
required channels there is no Telegram membership call. Access-check errors
or unverifiable membership **deny new admissions**, rather than falsely
confirming subscription. Requests are rate-limited before network checks.

Already accepted jobs remain owner-accessible through status, cancellation
and result download. The bot and API are distinct processes; the Telegram
bot's conversions are **not yet gated** and the bot must not open the API's
single-owner SQLite database as a second writer. The owner must provision
correct channel IDs and bot membership-inspection permissions before
enabling required channels. No mandatory channel is added automatically,
no campaign or payments are activated, and this is not a production
rollout. CI and merged-main verification are required before release.

## FileShape 4.6 — monochrome Mini App (verification pending)

The proposed Mini App refresh replaces the earlier blue palette with a consistent
**black, graphite and white** visual system. It covers the file-upload stage,
quick tools, PDF page controls, image preview, batch selection, server jobs,
history, profile, notices and empty/error/working states. The white primary
action and selected formats/pages have dark text; secondary controls use
graphite surfaces. The navigation has a visible selected indicator. The
Android/Telegram viewport retains bottom safe-area padding.

The styling includes explicit keyboard focus, touch-friendly action sizes,
reduced-motion support and forced-color selection outlines. Navigation announces
the current page and the local conversion format exposes its selected state.
Native Node regression checks reject chromatic CSS values and enforce key
contrast ratios and accessibility hooks. Actual server progress and status
semantics are unchanged; no fabricated completion or percentage is introduced.

No converter, storage, authentication, background processing, retention,
payment or deployment behavior changes in this revision. The design has not
yet been verified on a real Android Telegram WebView. A separate PR must pass
Python unit tests, native Node tests, TypeScript/Mini App build and Docker build,
then the merged-main GitHub Actions must pass before the version is called
complete. The selected design is intentionally monochrome, not dark blue.

## FileShape 4.5 — restart recovery and bounded cleanup

Recovery keeps the existing single-instance contract: an API process acquires
its private state-directory lock before changing interrupted records. Startup
removes unaccepted admission claims, marks accepted queued/processing jobs failed
and keeps completed metadata until its normal expiry. It does not execute inputs
again or recover result files from an earlier process generation. The regression
fixtures exercise actual SIGKILL of a process holding SQLite/artifact locks and
an unexpectedly killed parser subprocess, followed by a working conversion.

Periodic maintenance now retries known rejected-admission and terminal metadata
updates with a bounded reconciliation queue and at most 50 updates per pass. A temporary SQLite failure is
handled independently from artifact expiry and orphan cleanup. Missing or unsafe
completed artifacts are invalidated; private input directories belonging to
active jobs and open download leases stay protected. Failed deletion remains
charged to its reservation until a later cleanup succeeds, so an error cannot
silently free quota while the file is still present.

The workspace janitor keeps one directory cursor and one validated parent fd
between batches. Each sweep examines at most **500 root entries**, continuing on
the next 60-second maintenance tick instead of repeatedly scanning the same
prefix. One complete pass can therefore need several ticks on a large root.
Only old FileShape workspace generations are eligible. Directory locks protect
active generations even if their `.active.lock` marker disappears; verified
legacy marker-only locks are also respected. A missing marker on an old,
unlocked, private directory can be cleaned after a partial deletion. Symlink,
hardlinked, special or foreign markers remain for operator inspection. Cleanup
checks directory/marker identity relative to pinned fds and does not follow
replacement directory symlinks. This cleanup protocol requires the documented
POSIX/Linux deployment and local advisory-lock semantics.

Admission keeps the **256 MiB logical artifact-byte budget** and additionally
checks that reported free filesystem space covers the new reservation plus a
**64 MiB free-space floor**. The floor is an admission check, not allocated disk
blocks or a guarantee against another process filling the filesystem. Logical
reservations, the 1,000-artifact entry limit and physical limits are separate:
Compose still caps each service's `/tmp` with a 512 MiB tmpfs. Metadata remains
in its private persistent volume. Operators must monitor physical space and
retain deployment memory/CPU/process limits; these changes do not measure a
higher safe conversion concurrency.

Shutdown first closes admission and drains tracked upload/hash/validation
requests, then cancels/joins managed work before releasing artifact ownership and
SQLite. A shared shutdown task waits through repeated caller cancellation; an
individual cleanup failure does not skip closing the metadata store.
Legacy single-file/batch download responses now have a **120-second deadline**
and run their workspace cleanup in `finally`, including disconnect, timeout and
cancellation. Background downloads keep their existing four-stream/120-second
limits and retain their lease charge until the file descriptor closes.

**Operations:** use one API worker/replica on a trusted, private local filesystem.
A restart may leave old per-boot workspaces until they pass the one-hour stale
threshold and a janitor sweep reaches them; they are never advertised as
recovered results. If an unsafe-marker directory remains, stop all workers and
verify its location, ownership and file/link types before operator cleanup.
Deleting a live lock marker is not permission to delete its workspace. Preserve
the metadata volume when replacing containers; the backup/restore rules in 4.0
still apply. Source/result bytes need no backup.

**Local validation (4.5):** 279 Python tests, 54 native Node tests, TypeScript and
the Mini App production build passed. The Docker build and real read-only HTTP
smoke passed: idempotent create/retry, owned cancellation, foreign-result 404,
WebP result and compatible DOCX download. Tests cover actual process SIGKILL,
repeated shutdown cancellation, GC descriptor release and cleanup failure
isolation. PR CI and exact merged-main CI must still pass before 4.6. This is
source and container configuration, not a production deployment.

## FileShape 4.4 — owner-only cancellation and explicit retry

`POST /api/v1/jobs/{job_id}/cancel` authenticates the owner, cancels queued or
running background work and waits for subprocess/file cleanup before returning
a confirmed snapshot. Terminal jobs are idempotent no-ops. If completion wins
the race, the response stays completed and the result is preserved; missing
active handles return 503 rather than claiming cancellation. The Mini App stops
the previous poll while cancelling and applies only a response for the current
selected job. A network error is not confirmation of cancellation.

`POST /api/v1/jobs/{job_id}/retry` requires an owned failed/cancelled original,
a valid multipart reupload (`upload`, `action`, optional `pages`) and an
`Idempotency-Key`. It returns HTTP 202 with a new job ID, without changing the
original terminal record. Inputs are not retained longer on the server for this
feature: the new upload is size/content-checked again under the same limits.
The UI can reuse one valid in-memory source from this session or asks for a new
file after reopen/reset/expiry. PDF extract/remove retry ranges are explicitly
re-entered/validated, including the 150-unique-page cap; no missing page selection
is invented. No conversion is automatically replayed after restart.

Create also accepts `Idempotency-Key` (optional for older API clients; the Mini
App always supplies a cryptographically generated key). Keys are URL-safe ASCII
strings of 16–128 characters. SQLite stores an owner-scoped SHA-256 key digest
and fingerprint of actual upload bytes plus action/suffix/pages/retry parent,
not raw keys or files. An accepted identical request returns the same ID even
when artifact quota is full. A pending identical request returns 409 with
Retry-After; changed bytes/parameters under the same key return 409. Different
owners have separate namespaces. Pending and job insertion are atomic; rejected
admissions cascade away, while confirmed mappings expire with terminal metadata.
Startup removes unaccepted claims only after acquiring the exclusive process
lock. Idempotency lasts only as long as the associated metadata; it is not a
permanent exactly-once execution guarantee.

After an ambiguous response, the Mini App offers a **manual** resend of the same
in-memory intent/key; it never silently resubmits a file. One source up to 20 MiB
and its key/parameters stay only in memory, clear on reset/forget/expiry/owner
change and are not persisted in localStorage. The one-hour cache deadline is
deferred only while a bounded upload is active so an accepted new ID is not
lost at the expiry boundary. After reopen, only confirmed job references can be
restored; a missing source must be chosen again. Clearing local links does not
cancel server work. CORS allows the idempotency header only under the configured
exact origin, and retry bodies use the same pre-multipart ingress cap.

Optional controls browser regression: with Playwright/Chromium and the localhost
dev server, run `node tools/smoke-miniapp-controls.cjs`. It mocks Telegram/API,
checks cancel -> retry -> result and crosses parent-reference expiry during an
in-flight retry. This is not real Telegram WebView validation or deployment.

Validation at the merged 4.4 milestone: **225 Python tests, 54 native Node
checks**, TypeScript/Mini App and Docker builds passed. [PR #44](https://github.com/Dimash313/FileShape/pull/44)
is merged; [main Actions](https://github.com/Dimash313/FileShape/actions/runs/43382550867)
passed for commit `7a7b83f`.

## FileShape 4.3 — confirmed job states in the Mini App

Single-file server tools now create HTTP 202 jobs, display confirmed queued /
processing / completed / failed / cancelled states and offer an authenticated
result button after completion. Only XHR transferred-byte events produce upload
percentages. After upload the UI shows validation; conversion has a state label
rather than an invented percentage. The PDF page inspector, synchronous batch
photos and browser-only image conversion remain compatible.

Tracking observes one selected job, allows one in-flight poll, waits at least
10 seconds between status requests and stops on terminal states. A shared
client budget caps rate-limited API requests at 10/minute beneath the server's
12/minute limit. Failed requests back off; hiding the app or going offline
aborts the current status request and pauses polling. Returning online/visible
resumes without bypassing the request interval. Automatic observation is bounded
to 30 minutes / 180 attempts; a manual continuation is available after the limit.
Network errors retain the last confirmed state, never fabricate a failed job.

After an authenticated `/api/v1/session` identifies the owner, the Mini App can
restore up to 12 local job references (ID, action, timestamps), valid for one hour
from creation. It stores no filenames, file bytes, result blobs or Telegram
initData in persistent storage. Invalid, expired or private extra properties are
removed when references are loaded; while open, expiry is also scheduled. A
closed WebView cannot run cleanup, so stale storage is purged on the next open.
Blocked storage leaves current-session operation usable. Clearing references
only clears this device's links; it does not cancel server jobs or delete server
metadata. No unconfirmed upload is automatically sent again after a connection
failure or reopen. Results that expired or disappeared during server restart
show an explicit unavailable message.

Native Node regression tests use the existing TypeScript compiler, no new
service or test dependency. `cd miniapp && npm test` exercises polling,
hidden/offline/resume/disposal, finite budgets, owner-scoped reference retention,
XHR progress, response validation and authenticated result retrieval. This test
step is required in GitHub Actions before the production Mini App build.
For an optional browser smoke, start the dev server with
`cd miniapp && npm run dev -- --host 127.0.0.1`, then from the repository root
run `node tools/smoke-miniapp.cjs` with Playwright and Chromium installed.
`CHROMIUM_BIN` and `FILESHAPE_SMOKE_URL` can override the executable and localhost
URL. The script verifies queued/processing/completed, hidden/offline pause,
terminal stop, authenticated result headers and reopen without resubmission.
It uses mocks and writes only test screenshots under `/tmp`.

Mobile Chromium checks use test Telegram/API responses; they do **not** establish
real Android Telegram WebView compatibility or production deployment. Owner
cancel/retry controls are documented in the 4.4 section above.

## FileShape 4.2 — asynchronous conversion API and private result downloads

`POST /api/v1/jobs` accepts the same multipart `upload`, `action`, and optional
`pages` as the single-file converter. Signed Telegram authorization is required.
The API validates the operation, actual upload size and content identification
in a bounded subprocess, safely stores a private temporary input and responds
**HTTP 202** with `job_id`, `state`, `created_at`, `updated_at` and a status
`Location` header. Invalid uploads are rejected before acceptance. Unaccepted
metadata reservations are removed so invalid/overloaded requests do not consume
the 1,000 accepted-record capacity.

Use authenticated `GET /api/v1/jobs/{job_id}` for state and
`GET /api/v1/jobs/{job_id}/result` for the completed file (or JSON inspection
result). A known ID never bypasses the owner check: other owners and missing
records both return 404. Pending results return 409; failed/cancelled, expired
or unavailable results return 404. Download filenames are server-controlled;
no original filename is retained. Downloads are repeatable during retention,
carry no-store/nosniff headers and require the initData header, not a public URL.

Results live for **one hour after completion**, with cleanup every 60 seconds
and on quota reservation/access. Inputs are deleted on success; rejected,
failed and cancelled operations release files. A 256 MiB logical artifact-byte
budget reserves input plus worst-case 50 MiB worker output before upload,
then shrinks to actual completed files. The 1,000-artifact count also bounds
filesystem overhead; use the deployment tmpfs/disk limit for physical space.
Conservative reservations can reject a burst before the 20-place dispatcher
queue fills. The existing 20 MiB input, 45 MiB accepted output, subprocess RAM,
CPU and execution limits remain. Upload saving has a 30-second deadline;
preacceptance validation/admission waits at most 90 seconds plus cancellation
cleanup. Downloads are limited to four concurrent streams and 120 seconds.
Open downloads pin their disk quota until closed, including during expiry.

The manager uses fixed consumers and submission handles, with no task spawned
per background HTTP request. Status reaches completed only after verifying and
finalizing output. SQLite errors, timeouts, worker exceptions and queued/running
cancellation are cleaned up. Shared process execution remains bounded across
old and new endpoints. The queue snapshot now counts actual manager operations
and both bounded waiting rooms; it is still per process, not a throughput metric.

**Restart/operation limits:** metadata survives restart; uploads/results do not.
Graceful shutdown cancels work, waits for subprocess cleanup and deletes this
boot's artifacts. A crash leaves locked-workspace artifacts that the bounded
startup/periodic janitor removes once older than one hour and unlocked. No job
is replayed. Use a trusted private local filesystem and one API worker/replica.
Artifact files remain outside SQLite and the metadata backup volume. Rejected
new jobs can return 429 (queue full) or 503 (quota/store/shutdown), with Retry-After
where appropriate. Keep disk monitoring and the configured container limits.

The old `/api/v1/convert` and `/api/v1/images/pdf` routes remain compatible.
The Mini App still uses those routes until the 4.3 frontend integration; this
backend release does not yet add live polling or a cancel/retry button. No
public deployment or conversion recovery is claimed.

## FileShape 4.1 — bounded internal JobManager

Production HTTP conversions now dispatch subprocess work through `api/job_manager.py`: a fixed number of consumers, a bounded queue, a 50-second outer operation deadline and explicit error/cancellation propagation. The existing shared HTTP admission limit and subprocess CPU/RAM/output/time limits remain in force. Worker count stays at the configured value (default 3), with no throughput claim or increase to 10.

Cancelled callers wait for subprocess cleanup before deleting their workspace. Shutdown stops admission, cancels pending/active operations, waits for their cleanup and joins consumers before closing SQLite. Repeated shutdown is idempotent; an operation exception does not kill its consumer or lose subsequent work. Operations must cooperate with cancellation; the production subprocess runner terminates/reaps its process group. This manager is local to one process, not a durable execution queue or an HTTP 202 API. Existing HTTP conversions remain compatible. Early IDs and background result downloads follow in 4.2.

## FileShape 4.0 — durable metadata for real HTTP conversions

Both existing conversion endpoints now use SQLite metadata after API startup. Disabling ASGI lifespan fails conversion admission and readiness closed instead of silently falling back to memory. Opaque IDs, Telegram owner IDs, states and timestamps survive restarts; no file names, paths, contents or results are stored in SQLite. The authenticated status endpoint remains owner-only. Completed metadata does **not** mean that a result is available for a later download: results still stream in the original HTTP response and are then deleted.

The store holds at most 1,000 records. Capacity checks and insertion are one SQLite transaction; active records are never evicted. Terminal records expire after one hour, with cleanup on access/admission and every 60 seconds while running. At startup, an exclusive process lock is acquired **before** interrupted queued/processing records are marked failed. A second API process using the same state directory fails startup without changing the first process's jobs. Jobs are never replayed automatically.

**Operation:** use one API worker, one replica and a private service-owned local state directory (0700). Set `FILESHAPE_STATE_DIR` for local execution (default `./state`). Docker Compose mounts the named `job-metadata` volume at `/app/state`; preserve it across container replacement. `docker compose down -v` deletes metadata. Do not use an untrusted/shared/network filesystem or change the state directory to bypass the lock. Shut down all API processes before restoring metadata; restore the database as 0600 inside a 0700 directory owned by the container service user. Prefer SQLite's backup API for an online backup; copying a live database without its WAL is unsafe. Retain backups no longer than the stated metadata retention policy. No uploaded files need backup.

Cancellation while queued or processing closes uploads and marks cancelled; worker errors and workspace-creation failures release worker capacity and leave terminal metadata. A hard restart marks interrupted operations failed; file recovery, background creation, later result downloads and history enumeration remain scheduled for later versions. SQLite updates are short serialized operations; throughput still needs measurement on the target host. This change is source code and container configuration, not a deployment.

## FileShape 3.9 — SQLite metadata hardening before live integration

The standalone SQLite metadata store now tightens database file permissions to owner-only (0600 on POSIX), rejects symlink/non-file database paths, and uses SQLite FULL synchronous mode for durable transaction commits. Files are created with mode 0600 before SQLite opens them. Existing WAL/SHM/journal files are checked before connection; symlinks, hardlinks and non-regular files are rejected. Initialization failures close the connection. Tests cover competing transitions from two connections, stale updates, legitimate processing cancellation, private sidecars under a permissive umask and connection cleanup.

**Deployment caution:** This is not a complete defense against a hostile process that can replace parent directory entries; configure a private, service-owned directory on a trusted filesystem and protect its backups and WAL/SHM files. Run the service with a single worker until a shared job-store migration and multi-process startup semantics are designed. The live API still uses its existing in-memory job registry. No persistent files or restart recovery.

## FileShape 3.8 — SQLite job metadata persistence prototype

Adds a standalone `api/durable_jobs.py` SQLite-backed metadata store and tests for persistence across reopen, owner-only access, strict lifecycle transitions, terminal metadata expiry and explicitly marking interrupted queued/processing records **failed** after a restart. Only job IDs, owner IDs, states and timestamps are persisted; no file names, file paths, uploads or results. SQLite transactions guard state updates against stale transitions.

**Not yet enabled in production conversion endpoints.** The active API still uses the in-memory registry from 3.6. This module is a tested foundation for a later migration, **not** a persistent processing queue or restart recovery. Recovery deliberately does not replay jobs. Multi-replica ownership, bounded retention scheduling, filesystem encryption/permissions and safe durable upload/result storage require further design.

## FileShape 3.7 — job status in session history

The Mini App now reads `X-FileShape-Job-Id` from successful single-file and batch conversion responses, attaches the ID to the local session-history entry, and offers a manual **Проверить статус** action. This calls the authenticated, owner-only `GET /api/v1/jobs/{job_id}` endpoint with an eight-second timeout and validates the response. Statuses are shown alongside recent operations; locally converted images do not receive server IDs. No background polling or fabricated progress percentage.

**Limits:** IDs become available only after successful conversion; history is session-local, server metadata expires, and neither uploaded files nor results are persisted across restarts. A completed job status is metadata only, not a downloadable server copy.

## FileShape 3.6 — conversion job lifecycle and owner-only lookup

Single-file and multi-image conversions now register in-memory job IDs and transition through queued, processing, and terminal states. Successful responses include `X-FileShape-Job-Id` (for both JSON info and downloaded files); authenticated `GET /api/v1/jobs/{job_id}` returns the caller's job state, timestamps and opaque ID, without filenames or files. Cross-user and nonexistent IDs both return 404. The existing request rate limit applies. Job entries expire after one hour in a bounded registry.

**Important:** This still uses synchronous HTTP conversions: the client receives the ID **only after success**. It is not yet a live polling API for the uploading client, does not store files, does not survive restarts and cannot resume failed or interrupted work. Future versions will add early job-ID creation and persistent worker storage only after designing safe retention and recovery.

## FileShape 3.5 — private job metadata foundation

Adds `api/jobs.py`: a bounded in-memory registry for cryptographically random job identifiers, explicit `queued → processing → completed/failed/cancelled` transitions, owner-only lookups that hide whether another user's ID exists, terminal-entry expiry, capacity enforcement that never evicts active entries, and process-shutdown cleanup. Seven regression tests cover state transitions, isolation, TTL, capacity and invalid owners.

**Scope:** This is a tested backend foundation only. The registry is **not yet connected to conversion routes or the Mini App**; no job IDs are returned to users and no job-status endpoint exists in this version. It contains no files, filenames or personal profiles, and it does not persist across restarts or recover interrupted work. Future versions must integrate request lifecycles, address multi-process ownership and implement persistent storage before promising background jobs or recovery.

## FileShape 3.4 — visible queue load (not job recovery)

Adds authenticated `GET /api/v1/queue` with coarse per-process counters: configured worker capacity, workers in use, number waiting, waiting-room limit, and whether the API still accepts conversion requests. It uses existing signed Telegram Mini App authentication, shares the per-user 12-requests/minute rate limiter, and is returned with `Cache-Control: no-store`. No usernames, Telegram user IDs, filenames, or uploaded content are returned.

The Mini App profile now has a manual **Обновить** button to show the snapshot. It is a one-time server-state sample, not a progress percentage, job status or an estimate of when a particular user's file will finish. Counters reflect a single API process, not totals across replicas. Tests cover auth, data minimization, active/waiting numbers and shutdown state.

**Next foundation steps:** durable job IDs, explicitly scoped job lifecycle and safe metadata retention. Version 3.4 still does **not** persist uploads, create background jobs or restore conversions after process crashes.

## FileShape 3.3 — graceful queue shutdown

When the API process begins a graceful shutdown, the in-memory admission queue closes: new requests are rejected and waiting conversions wake promptly with HTTP 503 and Retry-After, rather than remaining stuck until the 90-second queue timeout. Added tests for waiting requests, closing-state admission and a simultaneous slot-release/shutdown race to prevent permit leaks.

**Important:** This does **not** persist or resume uploaded jobs after a crash or restart. Active jobs may still be interrupted by server termination. Durable job IDs, external storage and a persistent shared worker queue require a separate design and deployment.

## FileShape 3.2 — bounded in-process waiting queue

Single-file conversions and multi-image PDF jobs now share an in-process waiting room (20 waiting requests maximum, up to 90 seconds of waiting). The worker count is still configured with `FILESHAPE_MAX_CONCURRENT_JOBS`, defaulting to 3 and supporting up to 10 when hardware has been verified. When capacity is occupied, new requests wait for a semaphore slot in arrival order rather than immediately receiving HTTP 429. If the waiting room is full, the server returns HTTP 429 with Retry-After; if waiting times out, it returns HTTP 503 with Retry-After. The request remains connected and the Mini App shows an honest waiting/processing indicator without inventing percentages. Tests cover shared single/batch admission, 10 active workers plus an eleventh waiter, queue overflow, FIFO behavior, cancellation and timeout cleanup.

**Limits:** This is **not** persistent background processing. The queue is local to one API process and does not survive restarts; the client must keep the request open, and reverse-proxy HTTP timeouts must allow queued requests to finish. Each queued multipart upload may use temporary disk space. Multi-process deployments need a separate shared queue and global worker limits before increasing traffic.

## FileShape 3.1 — configurable worker concurrency

The maximum number of simultaneous conversion jobs is now configurable with `FILESHAPE_MAX_CONCURRENT_JOBS` (integer 1–10). Default remains 3 until real server memory and CPU capacity have been measured; setting 10 is an opt-in deployment decision. A worker can use up to 512 MiB, so ten workers may need approximately 5 GiB of RAM before API/OS overhead. Includes validation tests. This is not a persistent queue, and capacity is per API process, not globally shared across replicas.

## FileShape 3.0 — shared capacity and cancellation regression milestone

The existing three-slot concurrency limit is now tested across both single-file conversions and multi-image PDF jobs, including overload rejection and recovery. An additional test verifies that cancellation restores capacity. Batch processing failure logs no longer include exception tracebacks. This is the first server-reliability milestone; a durable job queue, recovery after process restart, and persistent job state are not implemented yet.

## FileShape 2.9 — privacy-safe failure logging

Unexpected API and request-middleware failures now log only generic operational markers rather than exception tracebacks, which could expose sensitive filenames or uploaded document details. Added a regression test for private exception messages. The client still receives a generic error and malformed PDFs remain rejected by existing worker validation. This is pre-3.0 server hardening, not a live deployment.

## FileShape 2.8 — PDF selection regression tests

Added regression tests for page-range syntax, duplicate pages, ordering, 150-page selection limits, 250-page document limits, extract/remove output integrity, and rejection of invalid page selections through the authenticated API. This release focuses on automated safety coverage rather than new UI controls.

## FileShape 2.7 — actionable PDF selection feedback

The Mini App displays an accessible inline message when page selection is missing, malformed, exceeds the 90-character field limit or 150 selected-page limit, or would remove every page. The same validation blocks submission and informs the preflight summary. This is client-side guidance; the server still performs authoritative PDF checks.

## FileShape 2.6 — paginated PDF page grid

The PDF page-number picker displays 50 numbered buttons at a time, with previous/next navigation for documents containing more than 50 pages. Selected pages remain selected when navigating between blocks. Page navigation resets when selecting a new file or re-inspecting its page count. The 150-page selection cap and server-side checks remain in force. This is a page-number grid, not a PDF thumbnail renderer.

## FileShape 2.5 — bulk PDF page selection and safety

After PDF page-count inspection, users can select all pages (for extraction only), invert the selection, or clear it. The interface now enforces the server's maximum of 150 selected pages and prevents selecting all pages for removal. It also fixes a page-range splitting bug in the 2.4 grid, so ranges like 1-3 correctly mark each page. Server-side limits remain authoritative.

## FileShape 2.4 — PDF page number grid

After the user explicitly requests PDF page count, the Mini App displays an accessible grid of numbered page buttons for extract/remove operations. Tapping a page toggles its selection and synchronizes the existing manual input. Consecutive selections are compacted into ranges, with a bounded 90-character input and the existing server-side checks. The grid displays numbers, **not rendered PDF thumbnails**. Manual input and quick presets remain available.

## FileShape 2.3 — on-demand PDF page count

The Mini App can explicitly request PDF page count from the existing authenticated server endpoint, displaying the result before editing. Once known, page-range validation is limited to the actual number of pages. Selecting another file resets the count. This sends the PDF to the server only when the user requests inspection; it is not an offline PDF parser or visual page preview.

## FileShape 2.2 — PDF page selection shortcuts

The Mini App now provides touch-friendly shortcuts for selecting the first page, pages 1–3, pages 1–5, and clearing the selection. The page input still supports comma-separated numbers and ranges. Client-side validation rejects zero, reversed ranges, values over the PDF processing limit of 250, and malformed syntax before upload. The backend remains authoritative and rejects pages that do not exist in the actual document. This milestone does not implement visual PDF thumbnails or page drag-and-drop.

## FileShape 2.1 — local image preview

The Mini App displays the selected JPG/PNG/WebP image before conversion using a browser object URL; the URL is revoked on file change/unmount. The preview itself stays on the device. PDF files show an honest file overview and link the user toward the existing page-count operation; rendering individual PDF pages is not yet implemented. This milestone does not add server-side image storage.

## FileShape 2.0 — editor workflow foundation

The Mini App now shows a three-stage file workflow (selection, settings, result), a preflight summary of the chosen server action, and inline page-range validation before submission. Operation buttons and file replacement are disabled while a conversion is running, preventing accidental state changes during an in-flight request. Archive descriptions now accurately reflect the current ZIP listing capability. This is the first editor milestone, not a claim that every editing tool or a full preview is implemented.

## FileShape 1.9 — conversion output verification

The pre-2.0 regression suite now exercises real authenticated API requests and worker subprocesses across image conversion (PNG/JPEG/WebP/PDF/compression), PDF editing (rotate, extract, first page, remove, info), and TXT/DOCX conversion. It parses resulting images, PDFs and Word documents instead of relying only on HTTP status codes. These tests cover representative generated fixtures, not the full variety of real-world files or deployment performance. Further format-specific tests and hardware stress tests remain release requirements.

## FileShape 1.8 — crash-recovery temporary workspace cleanup

The Linux API now uses private temporary workspaces with held advisory locks. At API startup it scans at most 500 workspace entries and deletes only FileShape workspaces older than one hour whose locks are no longer held. Active, recent and unrelated directories are preserved. Regression tests cover these cases. This is bounded startup recovery, not a periodic disk janitor; operational disk monitoring and container restart policy are still required.

## FileShape 1.7 — cancellation-safe temporary file cleanup

Both single-file and multi-image API handlers now explicitly clean their temporary directories when an asyncio request task is cancelled. Regression tests cancel an in-progress worker and assert that temporary files are removed and all three API processing slots are available again. This covers application-level task cancellation; a hard OS crash still requires host-level temporary-storage housekeeping.

## FileShape 1.6 — descendant process cleanup

On POSIX, conversion workers run in their own process session. When a request completes, times out or is cancelled, the API signals the worker's entire process group, preventing lingering FFmpeg grandchildren. Linux integration tests check that a timed-out worker's spawned grandchild no longer runs. Non-POSIX platforms still terminate the direct worker only. This is process lifecycle hardening, not a complete OS sandbox.

## FileShape 1.5 — malformed file regression tests

Integration tests exercise the actual API subprocess worker with truncated PDFs and PNGs, damaged ZIPs, unsafe ZIP paths, invalid DOCX containers and non-UTF-8 text. Each case expects a controlled error, and selected tests verify that valid conversion still works immediately afterward. Multi-image PDF recovery is also covered. These are generated test fixtures, not an exhaustive corpus or proof that hostile documents are harmless. Fuzzing and tests against diverse real-world files remain necessary before release.

## FileShape 1.4 — concurrent request regression tests

Automated ASGI tests now simulate three simultaneous conversions, verify that a fourth receives HTTP 429 while slots are occupied, and confirm processing slots are restored after successful and failed work. Tests replace the expensive worker with a deterministic stub, so they verify **admission and recovery logic**, not throughput, real conversion performance, memory consumption or production load capacity. Full stress testing on deployment-class hardware remains a release gate.

## FileShape 1.3 — privacy-safe diagnostics

Each API HTTP response includes a random `X-Request-ID` for troubleshooting. The server logs only that ID, a fixed route category, HTTP status and elapsed milliseconds; it deliberately excludes file names, contents, Telegram authentication data and user identifiers. Unknown URLs are grouped as `other`. This is basic observability, not full production monitoring or a load-test result. Operators should still configure log retention, access controls and reverse-proxy privacy settings before deployment.

## FileShape 1.2 — operational readiness

The API now exposes two distinct probes: `GET /health` for lightweight process liveness, and `GET /ready` for dependency readiness. The latter checks that FFmpeg and FFprobe are installed and temporary storage is writable; it returns HTTP 503 if a dependency is missing. Neither probe exposes environment variables or user files. Readiness is an operational signal, **not** proof that all converters work or that the service is production-ready. Monitoring, deployment orchestration and live tests remain pending.

## FileShape 1.1 — isolated API processing

Server-side uploads now undergo content signature checks before format parsers run: PDF magic bytes, JPG/PNG/WebP decoder identification, ZIP/DOCX container recognition, basic audio headers and binary TXT rejection. A renamed file cannot bypass these checks by extension alone. Single-file and multi-image endpoints both enforce validation. A streaming ASGI ingress guard also enforces the total multipart request size from actual received bytes (including when Content-Length is missing), before multipart parsing. Tests cover valid and mislabeled files.

**v1.1 hardening:** API conversion and file inspection now run in disposable subprocesses with a 45-second wall-clock timeout; on Linux, workers also have address-space, CPU and output-file caps. Timed-out processes are killed and reaped. This is process-level containment, **not** a complete sandbox (no filesystem/network namespace or seccomp). The Telegram bot's own handlers are not yet moved into these workers. Further release gates include multipart parser limits beyond the 21 MB ingress cap, crash recovery, load testing and live Android/Telegram verification. This commit does not imply those gates are complete or that the service is deployed.

## FileShape Studio Mini App (v0.9 UI, server hardening v1.1)

A mobile-first dark-blue React + TypeScript interface is in `miniapp/`. Four tabs, browser-side JPG/PNG/WebP conversion, downloadable results retained in limited session memory, and an **authenticated Python API** for supported file tools.

The Mini App now sends selected files to `/api/v1/convert` using **Telegram.WebApp.initData** in the `X-Telegram-Init-Data` header. The server validates the Telegram HMAC signature with `BOT_TOKEN`, validates `auth_date` (max age one hour), and derives user ID from the signed data. **Never trust initDataUnsafe or a user ID sent by the browser.**

Supported Mini App API actions:
- PDF: count, first page, select pages, remove pages, rotate 90 degrees
- Images: create single-page PDF, optimize to WebP (plus local JPG/PNG/WebP conversion)
- Batch photos: combine 2–8 JPG/PNG/WebP into a single PDF in chosen order; total incoming size up to 20 MB and decoded pixel limits
- Audio: inspect, convert to MP3/OGG/WAV
- Documents: DOCX ⇄ TXT, text info
- ZIP: list contents (extract/build still available through Telegram bot, not Mini App)

No accounts, payment processing, persistent file history or production monitoring exist yet. Upload progress uses the browser's actual transferred-byte events; **server processing has no percent-complete measurement**, so the UI only displays a processing state after upload. The history lists up to 12 operations, retaining downloadable blobs for at most four recent results with a combined 35 MB in browser memory (no persistent storage). API temporary files are removed on completion; size limits (20 MB input, 45 MB output), per-user request rate limits and a global concurrency cap are enforced. API clients must run inside Telegram; ordinary browser previews can only use local image conversion.

### Preview locally

```bash
cd miniapp
npm install
npm run dev
```

Build assets for HTTPS hosting with `npm run build` (output `miniapp/dist`). Server actions are **not usable** in an ordinary browser, even during development, because they require signed Telegram initData.

### Production wiring (not deployed automatically)

1. Provision a Linux VPS with Docker Engine, Docker Compose, Caddy and a domain name. Point the domain DNS at that VPS.
2. Copy `.env.example` to a private `.env` and enter your genuine **BOT_TOKEN**. Add `MINIAPP_URL=https://your-real-domain.example`. Do not commit this file.
3. Run `docker compose up -d --build`. This starts the existing polling bot plus an API on **127.0.0.1:8000**, not exposed directly to the internet.
4. Build the Mini App using Node 22: `cd miniapp && npm install && npm run build`. Install its `dist` files at `/srv/fileshape/miniapp/dist` on the VPS.
5. Configure Caddy with the example `deploy/Caddyfile.example` (replace the domain). It serves the frontend and proxies `/api/*` to the API **under one HTTPS origin**. Caddy also applies a request-body limit.
6. Register the HTTPS Mini App URL in BotFather and open the bot's `/start` button. Test signed uploads, conversion and downloads before allowing public access.

The reverse proxy MUST use HTTPS and cap request bodies near 22 MB. The API itself also validates uploaded file sizes, but the HTTP multipart parser needs an ingress limit to avoid enormous pre-parsed requests. A same-origin proxy avoids needing CORS. `MINIAPP_ORIGIN` is optional and should only be set to a single exact HTTPS origin if serving across separate origins.

The deployment instructions are for an operator with access to a VPS. **The code being present on GitHub does not mean the Mini App or API is online.**

## Deploy with Docker Compose (Linux VPS)

This repository provides a container deployment template. **It does not automatically deploy or start a bot.** You need a Linux VPS with Docker Engine and the Compose plugin installed.

1. Clone the repository to the VPS and enter the project directory.
2. Create a private `.env` file on the VPS containing `BOT_TOKEN=<token from BotFather>`. Do not commit or paste your real token into GitHub.
3. Run `docker compose up -d --build`.
4. Check startup with `docker compose ps` and `docker compose logs --tail=100 -f fileshape`.
5. To update: `git pull --ff-only && docker compose up -d --build`.
6. To stop: `docker compose down`.

The container uses Python 3.12 and FFmpeg, runs as a non-root user, and has a read-only root filesystem, temporary working storage, limited memory/CPU/processes, and rotating logs. The bot uses **long polling**, so no inbound web port or domain is required.

**Important:** Only run **one polling instance** per bot token. The container restarts on failure, but no monitoring, backups, or managed hosting are configured. Test with private files before inviting users. The `.env` file remains on your VPS and should be restricted to the server administrator.

## Run locally

1. Install Python **3.11 or newer**.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Install FFmpeg (for audio). For example, on Ubuntu: `sudo apt-get install ffmpeg`. Verify with `ffmpeg -version` and `ffprobe -version`.
4. Copy `.env.example` to `.env`.
5. Put the token created in BotFather into `.env` as `BOT_TOKEN=...`. **Never commit your actual token.**
6. Start the bot: `python main.py`.

The process must remain running for long polling to respond. GitHub is only source control; creating a repository does not host the bot.

## Tests

```bash
python -m unittest discover -s tests -v
```

Automated tests also run in GitHub Actions for commits to `main`.

## Roadmap

- More advanced PDF manipulation and batch tools
- Rich DOCX editing and DOCX → PDF conversion
- Additional audio formats and advanced archive tools
- Persistent job queue, true server-side processing progress, refined navigation and PRO subscription infrastructure
- Hosted HTTPS deployment, production monitoring and persistent job management

These roadmap features are **not implemented yet**.


## FileShape 4.19 — owner advertising analytics

The owner-only Mini App dashboard now shows aggregate confirmed joins across
**all** campaigns, not only the first paginated batch, plus verified join
events over the last 24 hours, active campaign count, links pending Telegram
revocation, and links acknowledged as revoked. `GET
/api/v1/owner/campaigns/analytics` uses the same signed Telegram Mini App
authentication and server-configured owner ID as the campaign management API.

Metrics come directly from the durable SQLite campaign ledger and the
pseudonymous deduplicated join-event table. They are not impressions,
subscriber totals, retention, conversion rates or revenue. No fabricated
progress is shown. If the analytics request fails, the UI falls back to
explicitly page-scoped numbers. The new endpoint never exposes raw member
IDs or join digests. Time windows are based on recorded Telegram event
timestamps. Manual refresh is required.
