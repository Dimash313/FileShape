# FileShape HTTP capability manifest v1 (5.0.10 proposal)

**Status:** API discovery contract only, not a mobile application, website,
deployed release, payments activation or worker migration. Existing bot, API
and Mini App processing behavior and authorization remain unchanged.

## Read-only discovery

`GET /api/v1/capabilities` returns a JSON object:

- `schema_version: 1` for breaking-change detection;
- `surface: "http"` and `route: "/api/v1/convert"`: **only** the existing
  single-file HTTP conversion endpoint, not bot commands, batch APIs or
  future native/offline tooling;
- `classification: "filename_suffix_for_routing_only"`: supported suffix
  routing is informational. Uploaded bytes are **still** validated by the
  existing processing pipeline, never trusted by name alone;
- `operations[]`: stable, sorted `kind`, `input_extensions` and `actions`
  derived from the actual server action allowlist, not a speculative roadmap;
- `max_upload_bytes` and `max_result_bytes` refer to the **HTTP API's**
  current maximums, not mobile or bot transport limits.

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
