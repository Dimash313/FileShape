# FileShape API parity inventory — phases F1–F3

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
| PDF | info, rotate, first page, select pages, remove pages, merge multiple PDFs | same single-file actions; PDF merge via separate batch route | **PDF merge now has a dedicated HTTP route** |
| Images | JPEG/PNG/WebP/PDF conversion, WebP optimization | same single-file conversions; multi-image PDF via separate batch route | Batch PDF route accepts 2–8 images |
| Audio | MP3/OGG/WAV conversion, file info | MP3/OGG/WAV conversion, file info | Audio trim, tagging and video-audio extraction are not HTTP actions here; independent draft feature branches may exist |
| DOCX | info, export plain text | info, export plain text | Not layout-preserving |
| TXT | info, export DOCX | info, export DOCX | UTF-8 input only |
| ZIP | list, extract bounded files, create 2–5-file archive | list; create 2–5-file ZIP through separate batch route | **ZIP extraction is still bot-only** |
| Video | not in this architecture stack | not implemented | Do not advertise |
| Other formats | scoped to registered operations | not implemented | No guessed formats |

## HTTP entry points

- `POST /api/v1/convert`: one uploaded file, with current
  `api.conversion_catalog.SUPPORTED` allowlist; synchronous file or
  information response
- `POST /api/v1/pdf/merge`: merge 2–5 PDF files into a single PDF,
  preserving their upload order, with a 20 MiB **aggregate HTTP** input
  limit, shared PDF page limits and a private temporary workspace.
  This is a standalone authenticated batch route, not a `pdf:merge`
  action in `/api/v1/convert`.
- `POST /api/v1/zip/create`: build a ZIP from 2–5 arbitrary uploaded
  files, preserving order while safely flattening paths and de-duplicating
  filenames. 20 MiB aggregate HTTP input, bounded worker, private
  workspace; returns `fileshape.zip`. Not an action in `/api/v1/convert`.
- `POST /api/v1/images/pdf`: a separate multi-image request,
  **not** a `/api/v1/convert` action and not a generic batch converter
- `POST /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`,
  `POST /api/v1/jobs/{job_id}/cancel`,
  `POST /api/v1/jobs/{job_id}/retry`,
  `GET /api/v1/jobs/{job_id}/result`: bounded background work and
  owner-scoped status/download flow for supported single-file actions
- `GET /api/v1/capabilities`: non-personal discovery describing
  `/api/v1/convert` actions and all implemented batch routes
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

1. Review **the remaining ZIP extraction gap** separately. Returning
   multiple extracted files over HTTP needs an authenticated, bounded
   result protocol with secure per-file delivery and cleanup.
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
It does not claim ZIP extraction or an independent mobile
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


## Phase F3 — authenticated HTTP ZIP creation (draft)

The new `POST /api/v1/zip/create` mirrors the Telegram bot's existing
2–5-file ZIP bundle function behind an independent HTTP batch route
and the shared `ArchiveModulePort.create` worker. The response is
`application/zip` with filename `fileshape.zip`.

**Security boundaries:**

- Existing signed Telegram initData, entitlement rules, rate limits,
  per-owner job/quota admission and cancellation semantics apply
- HTTP multipart body is limited at ingress (including chunked
  uploads), with an independent 20 MiB **aggregate** input cap and
  20 MiB per-member ZIP cap; empty uploads are refused
- Server controls temporary on-disk paths (`zip_item_0` ... `zip_item_4`);
  client filenames are metadata only and are flattened/sanitized by
  the existing archive implementation (with duplicate name handling)
- Worker accepts strictly 2–5 inputs, refuses missing/symlink files,
  validates names/actual file sizes, runs under existing CPU/memory
  limits and exits after producing one bounded ZIP result
- Successful HTTP streaming defers workspace cleanup until send
  completes; errors, timeouts and cancellation clean up immediately;
  crashed workspaces match the existing orphan sweeper prefix
- The v1 read-only capability manifest describes this implemented
  batch route with `input_kind: "any_file"` and
  `accept_any_file_type: true`, without inventing a `zip:create`
  single-file action

Current HTTP ZIP extraction **does not exist** and must not appear
in the manifest. Standalone website and native app login is also
not implemented in this phase. Existing Telegram ZIP features
and their larger independent per-bundle limits are unchanged.

The PR remains draft because GitHub Actions jobs fail before runner
allocation (issue #101). Require real exact-head full Python/Mini App/
Docker checks and ZIP binary smoke tests before merging or releasing.
