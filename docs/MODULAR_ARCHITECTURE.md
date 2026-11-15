# FileShape — modular monolith, stable updates (phase A)

Status: architecture contract and migration plan, **not a completed refactor**.

## Goal

An update to audio should not require edits to video, PDF or archives and must not silently break them. Isolate failures and regressions; **no architecture can guarantee zero defects**. Use evidence-backed tests and staged rollout.

## Target logical dependency direction

```text
Telegram bot / Mini App / website / Android / iOS
                       |
             Versioned application API
                       |
          Operations and job orchestration
             /         |          \
      audio       video / PDF      archives/images/documents
             \         |          /
        Shared minimal contracts / file policy
                       |
        Infrastructure adapters (storage, queue, billing)
```

- Each format domain owns its validators, operations, format-specific errors and tests.
- No format domain imports another format domain. Cross-format operations (e.g. extract audio from video) belong to an explicit orchestration/use-case layer that coordinates independent adapters.
- Domain logic must not import Telegram, FastAPI, UI components, billing, SQLite, HTTP clients or deployment code.
- Shared contracts stay small and stable; avoid a giant global utils module.
- Clients call public application APIs, never internal file-processing functions directly. Authorization, quotas, temporary file ownership and cleanup are enforced by the application boundary.
- A change to one format must not silently change another format's supported operations, output naming, metadata or resource budgets.
- Prefer direct in-process calls with bounded subprocess execution. **Do not introduce per-format microservices** unless benchmarks justify the operational and network overhead.

## Current repository: do not confuse target with implementation

Existing `services/audio_tools.py`, `services/archive_tools.py`, `api/`, `main.py`, and `miniapp/` are real implementation paths. The target structure is **not yet fully implemented**. Existing service modules should be wrapped with compatible adapters before any relocation; do not bulk move files or rewrite imports in one PR.

## Migration in small reversible PRs

1. **A — map and protect:** inventory actual imports, conversion entry points, tests, quotas, cleanup, public API and format-specific behavior. Add an architecture test for new domain boundaries; no behavior changes.
2. **B — define contracts:** typed input/output/error contracts and an explicit operation catalog with compatibility tests. Maintain old import paths.
3. **C — extract one format:** start with audio or archives behind an adapter, with golden-file and negative tests; preserve signatures and existing limits. Compare outputs before/after.
4. **D — repeat:** PDF, images, documents, video when implemented. Cross-format use cases live in orchestration, not mutual imports.
5. **E — integrate and verify:** cross-client contract tests, end-to-end conversion, auth/quotas, failure injection, latency/CPU/memory comparisons, rollback rehearsal.

## Required regression gate per module update

- Unit and real format fixtures for the changed domain, including corrupt and oversized inputs.
- Full existing Python suite, Mini App tests/typecheck/build and Docker build.
- Cross-format smoke matrix to prove unchanged tools still work.
- Cross-client API compatibility and auth/ownership/quota tests.
- Temporary file cleanup, cancellation, subprocess timeout and error propagation.
- Before/after benchmarks on representative files. No claim of zero overhead without measurements.
- Green exact-head CI, then merged-main CI; otherwise keep draft and do not deploy.

## Performance and operational decision

A Python package boundary adds negligible overhead relative to FFmpeg/PDF processing in typical workloads, but this is a hypothesis until benchmarked on FileShape. Separate OS processes or network services add serialization, startup and infrastructure costs. Start with a modular monolith and retain independent worker isolation only where needed for security/resource control.

## Existing architecture

Read [ARCHITECTURE_5.md](ARCHITECTURE_5.md) for current job/storage/accounting invariants and staged migration gates. This module plan supplements it and does not activate the unmerged distributed architecture, payments or new file size promises.

## Phase B1 — typed audio boundary (proposed PR, not yet merged)

The `services/audio_module.py` port defines `AudioModulePort` with two
existing operations: `probe(source)` and `convert(source, target, format)`.
An in-process adapter delegates to unchanged `services.audio_tools` logic.
`api/server.py` routes its audio-info and audio-convert dispatch via that
adapter, while preserving public `audio:info`, `audio:mp3`, `audio:ogg`,
`audio:wav` action names and output filenames. No new queues or microservices.

### Entry-point inventory and current ownership

| Surface / path | Domain calls and status |
| --- | --- |
| Telegram bot `main.py` | Direct calls to `services.audio_tools`, `file_tools`, `archive_tools`, `document_tools`. **Not migrated in B1.** |
| API `api/server.py` | `_info_action`, `_transform`: audio now uses the typed port. Other formats still use existing services. |
| Worker `api/worker.py` | Validates staged input; delegates single-file dispatch to `api/server.py` functions. |
| Background jobs `api/background_jobs.py` | Uses the existing worker path and its job/usage controls; no new direct format adapter is introduced. |
| `api/conversion_catalog.py` | Shared API operation allowlists and suffix routing, **not** trusted content validation. |
| ZIP, PDF, images, documents | Retain existing modules and entry points; migrate in independently tested releases. |
| Video | Planned only; do not advertise a working video conversion API. |

### Behavior and compatibility

- Contracts are internal, not a new public endpoint. FFmpeg execution,
  file validation, upload limits, auth, quota gates, workspace ownership,
  cancellation, error propagation and cleanup retain their existing owners.
- Existing `probe_audio` / `convert_audio` functions stay importable
  for the bot, tests and other legacy call sites. Their return shape,
  error messages and output naming do not change in this step.
- Port compliance, delegation, errors, action allowlists and cross-domain
  dependency isolation have regression tests; real FFmpeg roundtrips are
  covered by existing `test_audio_tools.py`.
- Next: migrate the Telegram bot into the same port behind its own
  compatibility tests, and then introduce common error contracts and
  reliable output cleanup without changing public behavior in one step.
- No benchmark or full CI pass is claimed until the exact PR head has
  executed the required checks.

## Phase B2 — Telegram bot audio adapter (draft PR; not merged)

The existing Telegram handler `main.py` now calls the **same**
`services.audio_module.audio_module` contract as the API for audio probing
and MP3/OGG/WAV conversion. The bot still owns Telegram identity checks,
download transport, state, quotas, workspace lifecycle, result delivery
and local temporary-file cleanup. No new endpoint or background service.

The following user-facing behavior must remain unchanged:
- The existing `audio:info`, `audio:mp3`, `audio:ogg`, `audio:wav`
  inline buttons and accepted file types.
- The existing 20 MiB Telegram download and 45 MiB output caps, 10-minute
  FFmpeg duration limit and existing conversion preset settings.
- Audio conversion filenames `audio.mp3`, `audio.ogg`, `audio.wav`
  for bot results; API output filenames `converted.*` remain distinct.
- Unauthorized, unrelated and unsupported callbacks are rejected
  **before** downloading, quota reservation or invoking the audio module.
- The successful-delivery billing settlement and refund-on-error behavior
  remain owned by `metered_bot_work`, not the format adapter.

### Evidence and gates

New bot regression tests use mock Telegram transport and a mocked module
adapter to exercise callback routing, per-format target paths, successful
information reads, foreign-user rejection, malformed action rejection,
conversion errors and failed Telegram delivery with quota release.
Existing real FFmpeg tests and API conversion matrix still need to pass on
the final branch. These tests do **not** substitute for real Telegram
private-chat smoke tests or a fully executed GitHub Actions run.

**Follow-up:** extract a similarly minimal contract for a second format
domain, one PR at a time; audit how all clients share format capabilities.
Do not introduce per-format microservices or change shared storage/billing.


## Phase C1 — PDF domain port for the API (draft, unmerged)

The new `services/pdf_module.py` declares `PdfModulePort` and a
`ExistingPdfModule` compatibility adapter with five operations:

- `count_pages(source)`
- `extract(source, target, pages)`
- `rotate(source, target, degrees)`
- `merge(sources, target)`
- `remove(source, target, pages)`

It delegates to the existing bounded `services.file_tools` PDF functions.
The API single-file dispatcher uses this port for `pdf:info`, `pdf:first`,
`pdf:extract`, `pdf:remove`, and `pdf:rotate`. It retains the same
result filenames, action strings, page selection semantics, output content
validation and error propagation. The format module has **no** direct
dependency on FastAPI, Telegram, billing, or database/queue infrastructure.

### Why not move all PDF code immediately?

`services/file_tools.py` currently implements **both** PDF and images.
The new PDF port establishes a stable seam without risky mass relocation.
Physical extraction into separate `services/pdf_tools.py` and image
code can happen later under behavioral parity tests. Do not delete the
old public imports while the bot and existing tests depend on them.

### Preserved boundaries and next steps

- Authentication, per-user quota, staging, temporary-file cleanup,
  cancellation and subprocess limits remain the responsibility of the
  API/bot application layers and worker runtime.
- `pdf:merge` is a **Telegram-bot flow** using the existing legacy
  `merge_pdfs` service, not a newly exposed single-file API operation.
  The port includes `merge` now for that future bot migration.
- The Telegram bot deliberately still uses the legacy PDF functions in
  this phase. Its PDF page-selection FSM, multi-file merge behavior and
  billing remain untouched.
- `tests/test_pdf_module_contract.py` covers the port, delegation,
  generated real-PDF page fidelity, errors, action allowlists and
  legacy API output naming. The architecture guard forbids direct ingress
  and billing imports into the new PDF adapter.
- **Next phase:** migrate the bot's PDF info/edit/multi-file calls through
  the port, preserving callback security, state, result delivery and
  refund behavior with separate async handler regressions.
- No claim of completed full test suite, live Telegram validation,
  throughput or guaranteed absence of regressions until CI and
  production-like checks provide evidence.


## Phase C2 — Telegram PDF operations use the same domain port (draft)

All current bot PDF processing entry points in `main.py` now delegate to
`services.pdf_module.pdf_module` rather than importing the individual PDF
functions from `services.file_tools`:

| Bot flow | Port method | Existing result file |
| --- | --- | --- |
| PDF page information | `count_pages(source)` | Bot text response |
| Extract first page | `extract(source, target, "1")` | `first_page.pdf` |
| Rotate 90 degrees | `rotate(source, target, 90)` | `rotated.pdf` |
| Extract selected pages | `extract(source, target, pages)` | `pages.pdf` |
| Remove selected pages | `remove(source, target, pages)` | `without_pages.pdf` |
| Merge 2–5 PDFs | `merge(sources, target)` | `merged.pdf` |

The API and bot now share the *logical* PDF boundary but intentionally
retain their distinct user-facing response filenames and existing UI state
machines. `services.file_tools` still contains the original PDF implementation
and image tools; only imports/delegation changed in this phase.

**Existing ownership remains unchanged:** bot private-chat and callback owner
checks, FSM, upload/download restrictions, server-side entitlement and quota
reservations, active-operation cap, temporary directory lifecycle, result
size limit and Telegram delivery are outside the PDF port. The port does
not import Telegram, FastAPI, database, billing or infrastructure.

New `tests/test_bot_pdf_module.py` checks dispatch and output names, ordered
merge, selected-page behavior, access denial, unsupported callbacks,
conversion failures, download isolation and quota release on failed delivery.
It uses mock transport/adapter; real-PDF parsing and limits remain covered
by `test_pdf_module_contract.py`, `test_file_tools.py` and existing API
conversion tests.

**Next safe step:** introduce a separate PDF implementation module while
retaining `services.file_tools` compatibility re-exports, then add analogous
image module boundaries. Do not rewrite the whole project or enable
unshipped video operations. No completed CI, real Telegram validation or
zero-overhead benchmark is claimed until independently verified.


## Phase C3 — physical PDF implementation extraction (draft)

This phase **moves**, rather than duplicates, the original PDF logic:

- `services/pdf_tools.py` owns `_reader`, `parse_page_selection`,
  `pdf_page_count`, `extract_pdf_pages`, `rotate_pdf`, `merge_pdfs`,
  `remove_pdf_pages` and PDF-specific resource limits.
- `services/pdf_module.py` delegates **directly** to `pdf_tools`. PDF
  conversion logic no longer needs to import the image implementation.
- `services/file_tools.py` still owns the image functions and re-exports
  the existing PDF functions/constants as a **temporary compatibility
  facade**. Existing legacy `from services.file_tools import ...` callers
  remain valid, including third-party integrations and older tests.
- The original algorithms, error messages, page-count and selection
  constraints, output names, and upload/quotas/security controls were **not**
  redesigned. The operation bytes and formats need actual regression
  verification, not just a code review.

### Compatibility and the remaining coupling

The old PDF function objects are direct re-exports, so normal legacy calls
and imports preserve their behavior. Mocking/rebinding
`services.file_tools.pdf_page_count` in a test **does not override** the new
direct `pdf_module -> pdf_tools` path; tests of the domain adapter must
patch `services.pdf_tools` instead. This is an internal test seam change,
not a public file-processing API change.

The compatibility facade still imports PIL and PDF code to retain old
symbols. It must not be treated as the new domain. Clients should move to
the typed PDF port or dedicated PDF/image modules in future PRs. Avoid
cycles and remove the compatibility facade only after auditing callers.

### Required regression evidence

- Source-level dependency checks: PDF implementation does not import PIL,
  image helpers, Telegram, API or payment modules; no duplicated PDF
  implementation stays in `file_tools`.
- Legacy exports are the same underlying PDF function objects.
- Real generated-PDF extract/merge/rotate/remove tests, including invalid
  ranges and encrypted/oversized handling from the existing suites.
- Image conversion/optimization smoke tests demonstrate that the image
  paths still work.
- Exact-head full Python, Mini App tests/build, Docker build and
  production-like bot/API smoke checks before any merge.
- No capacity or performance improvement is claimed without measurements.

**Next phase C4:** physically extract the image implementation into
`services/image_tools.py`, retain legacy aliases and introduce an image
domain port, separately and under equivalent compatibility tests.


## Phase C4 — physical image extraction and shared API image port (draft)

Image processing and PDF parsing are now physically separate:

- `services.image_tools` **owns** `_open_image`, `convert_image`,
  `compress_image`, `MAX_IMAGE_PIXELS`, output presets and decoded-image
  protection. The original transformation algorithms and presets are not
  redesigned in this phase.
- `services.pdf_tools` continues to own PDF parsing and page editing;
  image conversion *to* a PDF uses PIL's PDF output capability and does
  not call PDF page-editing functions.
- `services.file_tools` has **no format algorithm implementations**:
  it re-exports both domains' original public functions and constants for
  existing callers. It is a transitional compatibility facade.
- `services.image_bundle` imports the image decoder directly from
  `services.image_tools` rather than the legacy facade.
- `services.image_module` declares a typed `ImageModulePort` with
  `convert(source,target,fmt)`, `compress(source,target)` and
  `bundle_as_pdf(sources,target)`. The existing image and image-bundle
  implementations remain behind its in-process adapter.
- `api.server._transform` uses the image port for all existing
  `img:JPEG`, `img:PNG`, `img:WEBP`, `img:PDF` and
  `img:compress` actions. `api.worker` uses it for the existing
  multi-image-to-PDF batch route.
- The Telegram bot's image callbacks still import the legacy
  `services.file_tools` exports. They are intentionally **not**
  migrated in this PR; that requires its own handler/usage regression tests.

**Compatibility:** public API action strings, input classification and
validation, result filenames, image-quality settings, resource caps,
authentication, user isolation, quota accounting, and temp-file lifecycle
are unchanged. The adapter does not itself authorize or account for work.

**Regression evidence added** in image module contract, image extraction,
image worker and import-boundary test files: actual generated images/PDFs,
wrong/unsupported inputs, output size/format, transparency handling, call
ordering, dependency isolation and unchanged routing. Existing bot/API
integration, malformed-file, image-bundle and conversion-matrix tests must
continue to pass. Test mocks must patch `services.image_tools` or the
port rather than expecting a monkeypatch of a legacy re-export to reach the
new implementation.

**Performance:** this adds in-process Python function dispatch, not
per-format network calls or microservices. No guaranteed zero overhead,
latency improvement or production capacity is claimed until benchmarks.

**Next:** a small PR to switch bot image callbacks to the same image port,
then continue to independent document and archive modules. Do not
advertise a Video API until its full processing and security chain ships.


## Phase C5 — Telegram image handlers use the shared image module (draft)

Telegram image conversion and optimization in `main.py` now call the same
`services.image_module.image_module` port used by the API. The operations
remain limited to the existing buttons: `img:JPEG`, `img:PNG`,
`img:WEBP`, `img:PDF`, and `img:compress`.

### Preserved user-visible contract

| Bot callback | Port operation | Bot output name |
| --- | --- | --- |
| `img:JPEG` | `convert(source, target, "JPEG")` | `converted.jpg` |
| `img:PNG` | `convert(source, target, "PNG")` | `converted.png` |
| `img:WEBP` | `convert(source, target, "WEBP")` | `converted.webp` |
| `img:PDF` | `convert(source, target, "PDF")` | `converted.pdf` |
| `img:compress` | `compress(source, target)` | `optimized.webp` |

The bot uses `services.image_tools.IMAGE_FORMATS` for the original format
extension mapping; no new format is accepted. It retains its existing
image-document and photo input semantics. The source image remains
downloaded to a per-operation private temporary directory, while the
result is delivered through the existing Telegram send mechanism.

**Ownership and billing remain outside the port:** the existing private
chat/user callback checks, allowed-action validation, input size checks,
FSM busy state, entitlement checks, quota reservation, concurrent operation
limit, download, output size checks, Telegram delivery, success/refund
settlement and directory cleanup are not moved or weakened.

The new `tests/test_bot_image_module.py` covers all five callbacks, exact
output names and menu categories, photo input, unsupported/foreign/oversized
requests rejected before processing, entitlement denial, processing failure,
Telegram send failure and output-too-large failure with quota refunds. The
real image parser/conversion, API and image-bundle regressions remain in
the earlier test suites.

The image module's **batch** operation is available to the API worker for
the existing multiple-photo-to-PDF flow, but the Telegram bot does not
have an equivalent multi-photo PDF workflow in this phase. Do not claim
a newly shipped feature.

**Follow-up:** document and archive domain contracts and cross-platform
capability alignment can proceed in separate PRs. No public endpoints,
auth mechanism, subscription product, dependency, or size limit was added.
All required exact-head CI and manual bot checks must pass before merge.

