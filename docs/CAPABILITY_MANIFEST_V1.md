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
  implemented `POST /api/v1/images/pdf` endpoint. It includes the
  accepted image suffixes, current minimum/maximum count and aggregate
  upload limit. It is **not** a `/api/v1/convert` action code.
  API ZIP creation/extraction and PDF merge are not implemented routes.

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
with a separate, strictly declared image-batch route for the current
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
