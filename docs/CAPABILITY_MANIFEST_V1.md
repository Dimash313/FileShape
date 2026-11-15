# FileShape HTTP capability manifest v1 (Phase F1 integration)

**Status:** API discovery contract only, not a mobile application, website,
deployed release, payments activation or worker migration. Existing bot, API
and Mini App processing behavior and authorization remain unchanged.

## Read-only discovery

`GET /api/v1/capabilities` returns a JSON object:

- `schema_version: 1` for breaking-change detection;
- `surface: "http"` and `route: "/api/v1/convert"`: **only** the existing
  single-file HTTP conversion endpoint, not bot commands or future native/offline tooling;
- `classification: "filename_suffix_for_routing_only"`: supported suffix
  routing is informational. Uploaded bytes are **still** validated by the
  existing processing pipeline, never trusted by name alone;
- `operations[]`: stable, sorted `kind`, `input_extensions` and `actions`
  derived from the actual server action allowlist, not a speculative roadmap;
- `max_upload_bytes` and `max_result_bytes` refer to the **HTTP API's**
  current maximums, not mobile or bot transport limits.
- `batch_operations[]` is a **separate route descriptor** for the actually
  implemented `POST /api/v1/images/pdf` image-batch and
  `POST /api/v1/pdf/merge` PDF merge endpoints. Each has its own
  accepted input suffixes, minimum/maximum file count, and aggregate
  20 MiB HTTP upload limit. Neither is a `/api/v1/convert` action code.
  API ZIP creation/extraction are not implemented routes.

The endpoint is public, returns no personal/account/payment/job metadata and
has `Cache-Control: no-store`. It cannot start work, award credits, or
replace signed Telegram authentication and server-owned quota checks.
The server deliberately refuses to invent suffix metadata for a newly added
kind. A future action or format needs its own reviewed implementation,
capability review, compatibility tests and resource/security gates.

## Limitations and rollout gates

A listed action means its server **route is implemented**, not that every
arbitrary input is safe or successful. Audio requires a deployed FFmpeg/
ffprobe runtime; some files will be rejected for invalid content, size,
duration, format compatibility or service capacity. This is not a guarantee
of on-device availability, every pairwise conversion, or availability at
all times. `/ready` remains the separate runtime readiness signal.

Future public web and mobile clients should consume this versioned response
through appropriate authenticated processing endpoints and their own
transport/identity adapters. Their local capabilities and provider sign-in
must be described separately. IhsanSoft is the publisher only; do **not**
establish a global IhsanSoft ID or cross-product account database.

No new packages, external APIs, paid providers, payments, advertising,
music, user-facing imagery or prohibited content are introduced.
`AGENTS.md` applies to every follow-up. Do not merge without final-head
Python, Mini App and Docker CI on GitHub; run post-merge main CI before
considering any deployment.

## Source and compatibility

This manifest reuses the unmerged design from PR #87 and extends it
with separately declared image-batch and PDF merge routes for the current
architecture branch. It is a description of HTTP **route availability**
only, not a promise that files are processable, runtime resources are
healthy, or a deployment exists. `schema_version: 1` stays stable
because the additional `batch_operations[]` field is additive; clients
must safely ignore fields they do not recognize. Future breaking
changes require a new schema version.

FileShape's existing processing API currently authenticates **Telegram
Mini App initData**. Public web and standalone Android/iOS clients
cannot assume that this API already implements their own account
sessions; future product-specific authentication must be designed and
security-reviewed separately. Do not invent a universal account system.

The upload and result caps are enforced per HTTP transport; they are
not the Telegram Bot API limits or a guarantee of concurrent capacity.
A capability listing does not reserve a worker, bypass user quota,
disable subscription access policy or authorize an operation.


## Phase F2 — bounded HTTP PDF merge through the shared PDF port (draft)

The new `POST /api/v1/pdf/merge` endpoint exposes the existing PDF
merge domain operation to authenticated HTTP clients through an
independent batch route, **not** a new action accepted by
`POST /api/v1/convert`. It accepts 2–5 PDFs, preserves upload order,
and uses the existing Telegram initData authentication, per-owner
accounting, rate limits, admission, subprocess isolation and PDF
format/page checks. New HTTP aggregate upload cap is 20 MiB and
merged output is capped at 45 MiB; this differs from the Telegram
bot's independent 60 MiB PDF bundle budget. No sharing of upload
paths or session state between users.

`api.worker` recognizes only explicit `pdf_merge` worker operation
and constructs controlled `pdf_0.pdf` ... `pdf_4.pdf` paths itself.
The count must be an actual integer between 2 and 5, not a Boolean
or a client-supplied path. Each source undergoes PDF byte-signature
validation before the unchanged bounded `PdfModulePort.merge` call.

Workspace prefix `fileshape_batch_pdf_merge_` deliberately matches the
established crash-recovery orphan cleaner, and normal responses
schedule temporary-workspace cleanup after streaming. Failed uploads,
rejected content, cancellation, timeouts and exceptions clean up
immediately. The route is protected by the existing byte-counting
ASGI upload guard, not only an untrusted Content-Length header.

The v1 capability manifest now advertises this real route under
`batch_operations`, alongside existing `/api/v1/images/pdf`.
It does not claim ZIP extraction/creation or an independent mobile
login. Real-payload tests in `tests/test_http_pdf_merge.py` cover
authorization, first-to-last page order, request bounds, bad/mixed
files, password-protected and over-page PDFs, worker count/path
validation and success/failure cleanup. Existing backend tests remain
the release gate.

No dependencies, paid features, advertising, third-party integrations,
user-facing imagery or religiously sensitive materials are introduced.
CI remains blocked before runner assignment (issue #101); do not merge
this draft or deploy until full exact-head Python, Mini App and Docker
checks and real-file smoke tests run and pass.

