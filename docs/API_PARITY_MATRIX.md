# FileShape API parity inventory — phase F1

**Status:** review-only, not deployed. The current HTTP processing API
is an existing Telegram Mini App backend. Future standalone website,
Android and iOS clients need their own authenticated sessions and UI,
not a claim that their public API is already complete.

The table describes the current code in the stacked architecture
branches, not a production deployment or a complete list of planned
operations. The new capability endpoint must advertise only real
HTTP functionality.

| File domain | Telegram bot | HTTP API | Notes |
| --- | --- | --- | --- |
| PDF | info, rotate, first page, select pages, remove pages, merge multiple PDFs | info, rotate, first page, select pages, remove pages | **PDF merge is bot-only** |
| Images | JPEG/PNG/WebP/PDF conversion, WebP optimization | same single-file conversions; multi-image PDF via separate batch route | Batch PDF route accepts 2–8 images |
| Audio | MP3/OGG/WAV conversion, file info | MP3/OGG/WAV conversion, file info | Audio trim, tagging and video-audio extraction are not HTTP actions here; independent draft feature branches may exist |
| DOCX | info, export plain text | info, export plain text | Not layout-preserving |
| TXT | info, export DOCX | info, export DOCX | UTF-8 input only |
| ZIP | list, extract bounded files, create 2–5-file archive | list only | **ZIP extraction and creation are bot-only** |
| Video | not in this architecture stack | not implemented | Do not advertise |
| Other formats | scoped to registered operations | not implemented | No guessed formats |

## HTTP entry points

- `POST /api/v1/convert`: one uploaded file, with current
  `api.conversion_catalog.SUPPORTED` allowlist; synchronous file or
  information response
- `POST /api/v1/images/pdf`: a separate multi-image request,
  **not** a `/api/v1/convert` action and not a generic batch converter
- `POST /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`,
  `POST /api/v1/jobs/{job_id}/cancel`,
  `POST /api/v1/jobs/{job_id}/retry`,
  `GET /api/v1/jobs/{job_id}/result`: bounded background work and
  owner-scoped status/download flow for supported single-file actions
- `GET /api/v1/capabilities`: non-personal discovery describing
  `/api/v1/convert` actions and the implemented image-batch route
- `GET /api/v1/usage`, `GET /api/v1/session`,
  `GET /api/v1/queue`: authenticated account/queue state; these
  are not a public provider-agnostic identity API
- `/health` and `/ready`: infrastructure health and runtime
  readiness; a manifest does not replace either

The existing endpoints require Telegram-signed identity for file
processing and private resource operations. The discovery route
contains no session, billing, job or filename data, and does not
authorize requests. Input file suffix routing is always followed by
server-side content validation; the client must not claim that a
supported extension guarantees successful conversion.

## Next steps for platform parity

1. Review **each missing operation separately**: PDF merge, ZIP
   extract and ZIP create need safe HTTP upload admission, per-owner
   job state, bounded multipart intake, result cleanup and storage.
   Do not surface them through the capability manifest before
   implementation, realistic security tests and actual CI success.
2. Define independent authentication and session adapters for the
   standalone website and mobile applications **without** requiring
   a universal IhsanSoft account. Reuse processing modules and
   per-product identity boundaries, not one global users database.
3. Design client-specific UI for browser, Android and iOS, with one
   brand/design system. The UI should disable actions not described
   by the server and must check live readiness/entitlement separately.
4. Verify real ZIP/DOCX/image/PDF/audio fixtures and failure cases.
   Benchmark CPU/RAM/worker pressure before deployment at scale.

**CI blocker:** issue #101 documents GitHub Actions failing with
zero runner steps. The architecture chain and this phase must remain
draft and unmerged until full exact-head Python, Mini App and Docker
checks actually execute and pass; local smoke tests and security review
are still required. No payment or new infrastructure is authorized here.
