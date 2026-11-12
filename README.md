# FileShape

A Telegram file editor and converter by **IhsanSoft**, written in Python with aiogram 3.

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
