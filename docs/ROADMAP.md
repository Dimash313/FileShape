# FileShape — product and engineering roadmap

> Status: living engineering plan, reviewed 2026-11-14. **Not** a public launch, payment enablement, deployment or production-readiness declaration. Every change requires its own branch, PR, green checks on the final head commit and a successful push-triggered main CI run after merging.

## Source of truth and agreed business rules

This document supersedes **proposed** prices, quotas and packaging in [BOT_PRODUCT_ROADMAP.md](BOT_PRODUCT_ROADMAP.md) where they disagree. Keep [ROAD_TO_5.md](ROAD_TO_5.md) as historical engineering gates, not an assertion that outdated pending milestones are still current. Source code and merged PRs determine what is actually implemented.

| Tier / pack | Allowance | Price | Operational caveat |
| --- | --- | --- | --- |
| Free | 10 operations / UTC day | 0 Stars | 20 MiB per file, target maximum one in-flight operation |
| Pro | 100 operations / UTC day | 149 Stars / 30 days | Target 100 MiB per file and three in-flight operations **only if verified** transport and deployment capacity permit; priority queue and batch tools are not shipped |
| Extra 10 | 10 non-expiring operations | 19 Stars | Spend daily allowance first |
| Extra 30 | 30 non-expiring operations | 49 Stars | Spend daily allowance first |

The usage day resets at **00:00 UTC**; successful jobs are charged once, invalid/rejected/failed/cancelled jobs do not consume operations. Reservations must remain protected from concurrent admission and duplicate retries. Packs persist until used. A verified, non-duplicated Telegram Stars transaction must precede any entitlement or pack grant; refunds/reversals require an auditable, consistent policy. Paid functionality and published balance displays must stay disabled until end-to-end accounting is enforced.

## Verified milestones and current gate

| Version | Status | Scope / evidence |
| --- | --- | --- |
| 3.9–4.18 | Previously merged | Durable SQLite job state, security and recovery, conversion APIs, Mini App, access controls and owner advertising infrastructure. Refer to PR history, not proposed features as evidence of deployment |
| 4.19 | Merged | Owner advertising analytics; PR #61 |
| 4.20 | Merged | Telegram home/navigation; PR #62 |
| 4.21 | Merged | Atomic SQLite usage ledger, Free/Pro allowances and packs **without** processing enforcement; PR #63 (PR #64 superseded) |
| 4.22 | Merged | Owner-scoped, read-only `GET /api/v1/usage`, explicit `enforced: false` and `purchases_enabled: false`; PR #65. PR Actions passed; post-merge main Actions must also be confirmed |
| 4.23 | Merged | Atomic quota-backed processing on bot/API/Mini App paths; PR #67, verify deployed behavior separately |
| 4.24 | Draft | Telegram Stars signed order/receipt/refund flow, PR #69; final-head CI passed but real Telegram test purchases and refunds remain blockers; checkout disabled |
| 4.25a | Merged | Read-only Mini App profile from signed `GET /api/v1/usage`, PR #71; balances remain API-owned and Stars checkout off |
| 4.25b | In review | Read-only Telegram bot profile via a new HMAC-scoped bot→API bridge; no invoice, receipts or balance grants |

### Ordered implementation plan

**4.23 — real usage enforcement (P0).** Inventory every executable conversion admission path, including legacy synchronous endpoints, background jobs, retry and direct API, plus bot callbacks and multi-file workflows. Define one operation per accepted **completed user-requested transformation**, not each input file or status request. Reserve exactly once using a server-owned key (prefer durable job ID), coordinated atomically with job acceptance where possible; compensate safely on all failed admission and terminal outcomes, including cancellation and restart. Handle day rollover, completed replay, lost responses, timeout and multi-worker races. Prevent quota bypass through alternate ingress. Cap concurrent operations server-side by verified tier rather than front-end assertions. Retain 20 MiB Bot API constraints. Add DB/HTTP/bot/restart/concurrency tests. Flip `enforced` only when every path is covered and tests prove it.

**4.24 — Telegram Stars (P0).** Only after 4.23: implement documented Stars digital-service invoice/payment flow with server-verified successful payment, durable unique charge IDs, pending/verified/refunded states, pre-checkout validation, idempotent grants for Pro/10/30 packs, grant reversal or debt policy for refunds, reconciliation and audit tests. No payment acceptance based on untrusted callback data. Test using supported Telegram test environment; keep purchase UI disabled until verified. No additional payment processor.

**4.25 — profile and plans (P1).** Stage A: render verified account allowances and Pro expiry in Mini App from the existing authenticated read-only API, with explicit billing-off and error states. Stage A2: bot read-only profile through the same API-owned ledger (no purchases). Stage B (only after 4.24 is verified): server-confirmed purchase history and purchase navigation. Show *real* authenticated remaining daily/pack operations, UTC reset, active Pro expiration and actual verified purchase records in bot and Mini App. Server-side authorization and cache-control on balances; never invent an amount/status. Clear errors and disabled purchase options when billing is unavailable.

**4.26 — premium navigation and file cards (P1).** Clean black/white/graphite design, responsive mobile widths, keyboard/accessibility, concise bot messages, precise file and operation states, honest progress/status, navigable menus and usable errors. Preserve all existing conversion tools.

**4.27+ — utility expansion and hardening (P2).** Prioritize measured demand for new file tools; expand batches and input sizes only after resource/load testing. Audio editing candidate: trim by explicit start/end timestamps (HH:MM:SS), validate range against probed duration, preview in Mini App only when supported, and export with accurate duration and codec/container compatibility. Audio metadata editor candidate: title, artist, album, year, genre, and optional cover art upload/replace/remove; preserve audio stream without transcoding where supported, reject unsupported metadata/container combinations safely, validate cover image size/type, and strip temporary uploads. Build bot-friendly timestamp forms and a usable mobile timeline; add FFmpeg/ffprobe integration tests, metadata round-trip tests, input bounds and failure cleanup. Ship in a separately scoped release after 4.23–4.26, not in the quota/payment PR. Further requested audio operations, prioritized after the foundational release: concatenate multiple recordings in explicit user-selected order, extract audio streams from supported video containers (e.g. MP4/MOV/MKV) with validated duration and size, adjust gain, trim leading/trailing silence, change playback speed, split recordings into timestamped parts, select audio compression/bitrate and convert stereo to mono. Verify codec/container compatibility and reject unsupported or excessively large inputs; prefer stream copy when safe, otherwise bounded FFmpeg transcoding. Multi-input flows must preserve input ordering, tenant isolation, atomic output delivery and temporary-file cleanup. Telegram video ingestion requires separate transport/size checks; do not advertise it as shipped before end-to-end tests. Prioritize trim, join, video-audio extraction and tags first; other operations follow measured demand. Complete durable inbound channel-event handling, owner advertising lifecycle, observability, fraud/abuse controls, retention and security audits. Treat client acquisition and monetization as separate business readiness gates, not reasons to bypass safety.

## Technical risks and controls

1. **Split bot/API ingestion:** different paths may bypass quotas; build a complete ingress matrix and end-to-end tests before enabling counters/payments.
2. **Reservation/settlement inconsistency:** crashes between accepted jobs and reservation, lost settlement, retries, cancellation and UTC rollover can overcharge/undercharge. Use transactional patterns, replay-safe state machine and reconciliation; never silently discard unsettled reservations.
3. **SQLite safety and contention:** keep `BEGIN IMMEDIATE`, bounded waits, private service-owned directory, regular non-symlink database and WAL sidecars, locked/CAS state transitions, consistent close/rollback and migration testing.
4. **User privacy and isolation:** verify signed Telegram identity at boundary; server-side IDs only; foreign-user IDs and replay cannot access files, job status or ledger data. Never store uploaded bytes in billing records.
5. **Telegram transport and server capacity:** standard Bot API file downloads are limited; do not promise 100 MiB or higher per-tier parallelism without measured deployment and supported transfer route. Keep CPU/RAM/disk/queue/time/bomb safeguards on both plans.
6. **Payments/refunds:** duplicate update delivery, reversed payments, spoofed callback values, partial grants and audit divergence. Stable transaction keys and operational reconciliation are mandatory.
7. **Deployment/runtime:** bounded temporary uploads/results, subprocess timeouts, bounded queues, recovery after crashes, secret management, Docker resource limits, migrations/backup/rollback and real mobile Telegram testing remain launch blockers.

## Definition of done for each version

- Read current `main`, tests, README, release history and recent Actions before editing.
- Separate branch, scoped PR, migrations and explicit rollback guidance where relevant.
- Regression coverage: successes, failure rollback, stale state, concurrency/replay, tenant isolation, rate/input limits and process restart.
- Python compile + full unittest suite; Mini App Node tests, TypeScript/Vite build; Docker build (all jobs green for **final** PR head).
- Merge only after successful required checks; confirm **push-triggered** `main` workflow for merged commit. Update this roadmap with actual PR links, verified outcomes and outstanding limitations.
- Never claim local/prod testing, throughput, Stars verification or payment revenue without evidence.

## Commercial launch checklist (all required)

- [ ] Quotas correctly enforce **every** bot and HTTP/Mini App ingress path.
- [ ] Release payment verification, idempotency, refund/reconciliation, operational audit with real test payments.
- [ ] Verify tier file size and concurrency claims under expected workload; preserve safe fallbacks.
- [ ] Perform auth/IDOR, parser/ZIP/PDF, resource exhaustion, SQLite/WAL, queue and data-retention security reviews.
- [ ] Verify backup, restore, migration rollback, storage deletion and monitoring on production-like Docker host.
- [ ] Run load tests, end-to-end real Telegram bot/Android Mini App tests, and error-flow regression matrix.
- [ ] Validate product wording, transparent pricing/renewal/refund handling and user privacy disclosures.
- [ ] Launch only with explicit production authorization and an incident/rollback procedure.


## FileShape 5.0 — architecture rebuild (proposed; staged)

Architecture migration design and mandatory invariants: [ARCHITECTURE_5.md](ARCHITECTURE_5.md). This is a **proposal**, not a deployed or benchmarked architecture. Implement contract-tested boundaries before replacing SQLite or in-process execution. Keep existing quotas, owner isolation, file cleanup and disabled Stars checkout intact. Proceed with measured phases A–F and separate PRs; do not claim 100,000 concurrent conversions without representative load tests. The earlier 4.26 premium UI milestone remains planned, with sequencing to be agreed after the architecture foundation review.

## Modular update-safe architecture — phase A

See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md) for independent
per-format modules, stable cross-client contracts, compatibility and
cross-format regression gates. The first PR adds architecture documentation
and import-boundary regression checks for existing audio and ZIP services;
it **does not** migrate runtime code or claim zero overhead. Refactor one
format at a time after baseline and contract tests; do not activate new
infrastructure or break existing entry points.

### Phase B1 — typed audio interface (in review; not released)

The audio domain now has an in-process typed port/adapter and the API
single-file dispatcher calls it. The Telegram bot still calls the existing
audio service directly; intentionally no bulk refactor. The public audio
actions, backend resource limits and FFmpeg functions remain unchanged.
See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md) for the ingress
inventory, compatibility tests and next migration steps. Do not claim
runtime parity or merge before exact-head CI and cross-client checks.

### Phase B2 — shared audio adapter in the Telegram bot (draft)

Telegram audio-info and audio-conversion handler paths now use the same
typed in-process module port as the API. Authorization, Telegram transport,
usage accounting and output limits stay in their existing owner layers.
Tests cover callback ownership, supported actions, successful delegation,
conversion failures and failed delivery with quota refunds.
See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md). This PR is not
deployed or verified by exact-head full CI. The other format modules
and the bot's existing interface remain unchanged.


### Phase C1 — independent PDF module contract (draft; not released)

Created a typed PDF module boundary, with the API delegating its existing
page information, rotation, extraction and deletion operations to the
compatibility adapter. The API action catalog and output names remain
unchanged; PDF merge remains a Telegram-only legacy flow. Real-PDF fixture
tests, dispatch/error tests and architecture import guards are included.
See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md).

The current shared `services/file_tools.py` still contains PDF and image
implementations; do not claim full physical separation yet. Next isolate
the bot's PDF calls in a separately reviewed PR. Do not merge or deploy
without required exact-head CI and manual verification of the affected
workflow.


### Phase C2 — PDF processing shared by bot and API (draft; not released)

Bot PDF information, first page, rotation, page extraction/removal and
multi-file merge now use the same in-process PDF port as API dispatch.
Public callbacks, page-selection FSM, result names, file-size limits,
quotas, temporary files, access checks and billing behavior are preserved.
A dedicated regression suite covers routing, error refunds, denied
access, delivery failure, ordering and filename compatibility.

The underlying PDF code still lives beside image tools in
`services/file_tools.py`; physical module extraction remains a future
separately tested phase. See
[MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md). No production
readiness or successful full CI is claimed for this draft PR.


### Phase C3 — physically separate PDF implementation (draft)

The PDF parser, page-selection logic, transformation functions and limits
are now defined only in `services/pdf_tools.py`. The typed
`services/pdf_module.py` port calls this implementation directly.
`services/file_tools.py` retains image operations and backwards-compatible
PDF re-exports, so existing imports keep working.

This is a mechanical code move, **not** a new user-facing feature or
production rollout. Dedicated tests assert legacy import identity,
standalone PDF dependencies, generated-PDF behavior and image stability.
See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md).

The next isolated phase should extract `services/image_tools.py` and
introduce an image domain port; avoid removing legacy exports until callers
are audited. Merge only after all required CI and representative real-file
regressions pass. No measured speedup or complete production validation
is claimed in this draft.


### Phase C4 — independent images implementation and API port (draft)

The image conversion functions have moved from `services/file_tools.py`
to `services/image_tools.py`; the old import paths remain as
backwards-compatible re-exports. `services/image_module.py` supplies
an in-process typed image interface, and API single-file conversion
plus the existing multi-image PDF worker route now use that interface.
No new client-visible actions, endpoint, billing, service or limit.

Dedicated image contract, extraction, worker and dependency tests are
included, alongside the existing real-file conversion matrix. The
Telegram bot still uses compatibility imports pending a separate
small PR. See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md).

A claim of "10/10" readiness requires actual exact-head Python,
frontend, Docker and real file-processing test evidence. The prior
GitHub Actions runs failed before executing job steps; do not treat
them as either successful tests or proof of a code regression.


### Phase C5 — image domain parity for Telegram bot (draft)

The existing Telegram bot image callbacks now delegate conversion and
optimization to the same typed `ImageModulePort` as the API. This keeps
all original formats, bot filenames, menu buttons, upload/output limits
and billing decisions. User-ownership checks and temporary files stay in
the bot; the shared domain module only processes images.

Dedicated asynchronous bot regressions cover all five callbacks, Telegram
photo input, unauthorized or unsupported actions, busy states, entitlement
denial, quota refunds and failed Telegram delivery. Existing real image
processing and API matrix checks remain required. See
[MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md).

Next separate domain PRs can migrate `services.document_tools` and
`services.archive_tools`, one tested release at a time. No new API
endpoints or supported formats are claimed here. Keep this PR draft
until parent PRs and full exact-head CI pass.


### Phase D1 — typed DOCX/TXT domain port and API integration (draft)

`services/document_module.py` introduces a format-specific interface
for inspecting DOCX/TXT files and converting DOCX -> TXT and TXT -> DOCX.
The existing FastAPI request dispatcher now uses it without changing
public endpoints, actions, output names, quotas or validation.
`services/document_tools.py` remains the bounded implementation,
including explicit plain-text-only document semantics; the Telegram
bot is not yet migrated.

New isolated adapter and real-file tests cover contract parity, parsing
limits, output filenames and cross-domain isolation. Next phase D2
should move Telegram DOCX/TXT callbacks behind this port separately.
The GitHub Actions pre-run infrastructure blockage is tracked as
[issue #101](https://github.com/Dimash313/FileShape/issues/101), with
a separate [CI PR #102](https://github.com/Dimash313/FileShape/pull/102).
These architecture PRs remain drafts until the full exact-head test
suite and dependent integration checks can execute and pass.


### Phase D2 — Telegram DOCX/TXT uses the shared document port (draft)

The four existing bot callbacks, DOCX/TXT information and DOCX->TXT /
TXT->DOCX export, delegate to `DocumentModulePort` already used by the
API. Existing bot-specific file names, visible text, menus, quotas, access
checks, temporary files and result delivery remain intact.

Handler regression tests cover owner/format validation and failed
conversion or Telegram delivery refunds. Actual Word/plain-text fidelity
continues to be covered by the original document and API conversion suites.
There are no new public endpoints or file types.

Next independently isolate existing ZIP archive operations with an
archive port and preserve path traversal/decompression limits. CI remains
blocked before runner allocation (issue #101); this PR must stay draft
until exact-head tests, Mini App checks and Docker all actually execute
successfully.


### Phase E1 — ZIP archive contract and shared API inspection (draft)

Created `services/archive_module.py`: a typed in-process port for
ZIP inspect, safe extract and bounded create. API `zip:list` uses
the port, preserving the public action and result format. Existing
Telegram archive callbacks retain their original service imports
until a separate handler migration (E2). No new ZIP API endpoints,
allowed actions, formats, limits, payments or dependencies.

Regression tests include original ZIP paths, duplicate filenames,
real archive roundtrip, malicious member names/symlinks, decompression
limits and unchanged cross-format dispatch. The existing
`services.archive_tools` implementation is unchanged.

The required complete GitHub Actions CI is currently blocked before
runner assignment (issue #101). All affected PRs stay draft pending
exact-head full Python, Mini App and Docker checks and real-file
smoke testing. No readiness or guaranteed absence of bugs is claimed.


### Phase E2 — Telegram ZIP operations through the shared archive module (draft)

`main.py` now calls `archive_module.inspect` for `zip:list`,
`archive_module.extract` for `zip:extract`, and
`archive_module.create` for Telegram ZIP bundle completion. Existing
callbacks, state-machine flow, two-to-five-file ZIP bundle order,
`fileshape.zip` name, per-user quotas, access checks, input/output
limits and Telegram result delivery have not changed. API ZIP
capabilities are still **read-only**.

New async bot handler tests cover operation routing, order and
filenames, entitlement and ownership, incomplete FSM state, ZIP
parser errors, failed Telegram sends and quota settlement/refunds.
Existing real ZIP security regression suites remain required.

Next work should review API feature parity without adding unsafe
multi-file endpoints and reconcile all stacked PRs once CI runners
are restored (issue #101). Exact-head full Python + Mini App + Docker
CI and real-file smoke tests remain a hard merge requirement.

## Phase F1 — versioned HTTP capability discovery and platform parity (draft)

Introduced the read-only `GET /api/v1/capabilities` endpoint for
future clients. Its versioned JSON describes only the existing single
file `/api/v1/convert` action allowlist and, separately, the real
`/api/v1/images/pdf` batch endpoint. It reuses the original
capability-manifest proposal in draft PR #87 rather than inventing
a competing protocol. It does **not** expand server processing,
authentication or payment behavior.

The documented parity matrix explicitly tracks Telegram-only PDF
merge and ZIP extraction/creation. Additional HTTP operations will
require independent authorization, input constraints, worker/batch
admission, secure result delivery, cleanup and tests, not merely
publishing a name in the manifest. Future website/Android/iOS
sessions must be designed independently and must not imply a
global IhsanSoft ID.

All stacked architecture changes remain draft/unmerged due to
GitHub Actions runner pre-start failure (issue #101). Full
exact-head Python, frontend and Docker CI plus integration tests
must pass before release.


### Phase F2 — authenticated bounded HTTP PDF merge (draft)

A dedicated `POST /api/v1/pdf/merge` multi-file HTTP route now calls the
existing `PdfModulePort.merge` implementation through the isolated
worker. Only 2–5 PDF uploads are accepted, with a shared 20 MiB **HTTP**
aggregate size budget (the bot's batch limit is different), a 45 MiB
result bound, the established PDF page limit, per-user admission, quota
settlement, a temporary workspace and orphan cleanup. Source filename
suffixes are checked before dispatch and bytes are validated in the
worker. Inputs are processed in upload order, and successful responses
return `merged.pdf` with no-store/nosniff headers.

`GET /api/v1/capabilities` lists the route as a separate batch
operation, not a `/api/v1/convert` action. The Telegram bot's PDF merge
is unchanged. Tests cover order, count bounds, invalid/missing PDFs,
spoofed files, encrypted/over-page PDFs, upload limit, temp cleanup and
worker payload validation. No ZIP create/extract HTTP endpoint, new
identity system, payment activation or outside services introduced.

CI is still blocked before runner allocation (issue #101). This
stacked PR must stay draft until exact-head tests run and pass.

## Phase F3 — authenticated bounded HTTP ZIP creation (draft)

`POST /api/v1/zip/create` uses the shared ZIP module in the
isolated worker, with 2–5 client-selected files, original order and
safe ZIP member naming. HTTP upload limit is 20 MiB total, with
independently enforced per-file/worker resource limits. The new
batch route uses existing private workspace lifecycle, Telegram
Mini App authentication, subscription and quota admission, output
streaming and cleanup. Existing bot flows remain unchanged.

The v1 HTTP capability manifest describes this real route under
`batch_operations` as accepting arbitrary file suffixes; it does
not add `zip:create` to the single-file action allowlist. Real
ZIP and worker contract tests cover integrity, names, limit and
failure cases. **ZIP extraction over HTTP remains missing.**

Next work should design secure owner-scoped extraction results
without treating a multi-file output as an atomic Telegram-style
message burst. Any web/mobile login needs independently reviewed
FileShape sessions, not a shared product-wide IhsanSoft account.

No new paid dependency, integration, content or media assets.
Keep all changes unmerged until exact-head CI completes on real
GitHub runners and malformed/large ZIP smoke tests pass
(issue #101).
