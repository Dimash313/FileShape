# FileShape — Universal Format & Editor Roadmap
Status: **product proposal, not implemented or deployed**. Created 2026-11-15. This supplements [ROADMAP.md](ROADMAP.md) and [ARCHITECTURE_5.md](ARCHITECTURE_5.md); it does not change approved Free/Pro pricing, quotas, privacy, security, billing or release gates.

## Approved rollout strategy: Telegram first, platform-ready from day one

**Release order:** (1) Telegram bot production launch; (2) public website; (3) Android and iOS applications. The existing Telegram Mini App is a client of the bot ecosystem, **not** a separate public mobile-app launch. Do not block bot launch on a complete website, app store distribution, Google/Apple sign-in or cross-product single sign-on.

**Design now, activate later:** one server-authoritative, versioned API and conversion capability registry for all future clients. Keep Telegram-specific transport, Stars invoices, Mini App initData and 20 MiB bot download limits in ingress adapters, not conversion business logic. Build portable, testable boundaries for authentication, authorization, user identities, entitlements, billing, jobs, workers, temporary artifacts and capability discovery. Maintain backward-compatible bot routes during migration.

### Product-owned FileShape accounts and subscriptions — future-proof contract

**Decision: do not create IhsanSoft ID, cross-product single sign-on or a shared IhsanSoft user database.** IhsanSoft is the publisher/umbrella brand and quality standard only. FileShape, NickScope and any future products independently own their accounts, user data, permissions, subscriptions and billing. Reusable technical libraries may be shared without shared production identities or cross-product access.

- **FileShape account:** one opaque internal `fileshape_account_id` per FileShape user across its Telegram bot, Mini App, website, Android and iOS. Provider credentials are separately verified linked login methods; Telegram ID, Google email and Apple relay email are not primary keys.
- **Bot launch:** verify Telegram identity using existing trusted bot/Mini App mechanisms. Create or map a FileShape account without extra signup. Preserve current identity behavior until migration and isolation tests pass.
- **Website:** add secure Telegram login and optionally verified email/Google login. Link identities only after proof of control of both; never merge solely by matching email.
- **Mobile:** add appropriate Google/Apple sign-in, restore purchases and account-deletion flows. Observe each store's purchase requirements; do not assume Telegram Stars checkout can replace store billing.
- **FileShape Pro only:** one FileShape entitlement across FileShape clients where platform policies allow. Validate receipts, refunds and grants server-side per payment provider. FileShape Pro does **not** unlock NickScope or any other IhsanSoft product.
- Price target: **149 Telegram Stars / 30 days** in bot; future local-currency prices target comparable user cost, not guaranteed exact equality. Existing bot/cloud quotas in ROADMAP.md remain authoritative.
- Future mobile **on-device** operations aim to have no artificial attempt-count limits and no third-party ad networks. Server/cloud processing remains resource-metered.
- Sync minimal FileShape-specific settings and favorites only when useful and authorized. Never permanently sync user files by default; enforce strict temporary artifact ownership and deletion.
- Account linking, recovery, unlinking, deletion and migration need audited protections against account takeover, duplicate subscription grants and cross-user data exposure.

### Deployment and engineering sequence

1. **Bot launch gate (now):** repair CI and review outstanding architecture/payment PRs; verify bot/API quotas, Stars test receipts and refunds before activation; secure job processing, cleanup, monitoring, backup/restore and real Telegram end-to-end tests. Launch only supported tools and only after operational approval.
2. **Shared contract foundation (in parallel, no launch delay):** versioned capability catalog, stable account/entitlement interfaces and typed API; preserve legacy adapters, keep features behind flags. Add tests showing Telegram ingress and future HTTP clients cannot bypass auth or quotas.
3. **Website (after bot):** build responsive frontend against the same authenticated API; signed uploads/downloads, explicit server limits, account linking and shared Pro entitlements; independently test browser session/CSRF/CORS and mobile browsers.
4. **Android and iOS (after website, parallel if capacity permits):** native/on-device conversion adapters for suitable formats, shared cloud API for heavy jobs, platform-specific purchase validation and restore, secure identity linking and app-store compliance. No requirement to upload every local file.
5. **IhsanSoft platform extraction (only when multiple products need it):** reuse generic, stateless technical libraries only when valuable; do not centralize product identities, billing or user data, and do not prematurely build microservices.

**Release discipline:** every implementation milestone uses a separate branch and PR; green final-head Python, Mini App and Docker checks; post-merge main CI; realistic load tests and owner approval for production rollout. This is an architectural commitment, **not** a claim that Google/Apple login, unified subscription or mobile apps already exist.

## Goal and truthful scope
Build one file studio for Telegram bot, Mini App, web, Android and iOS backed by a versioned **shared server-side capability catalog**. "All formats" means broad, extensible coverage, **not** every existing proprietary format or every pairwise conversion. Capabilities are explicitly distinguished as **read / inspect / edit / write / convert / batch**; support is directional and often lossy. Never advertise an unimplemented format. Client and transport limits remain independent of codec support.

## Target format families (proposed; not all shipped)

| Family | Candidate inputs / outputs | High-value operations | Caveats |
| --- | --- | --- | --- |
| Audio | MP3, WAV, FLAC, OGG/Vorbis, Opus, M4A/AAC, ALAC, AIFF, WMA, AMR, APE | Convert, trim, concatenate, split, gain, speed, normalize, extract from video, compress, channel/sample-rate conversion, metadata and cover art | Codec availability, licensing, duration and container compatibility vary |
| Video | MP4, MOV, MKV, WebM, AVI, MPEG, 3GP, TS, M4V | Convert, trim, join compatible streams, resize, compress, mute, extract audio, inspect tracks, poster frame, subtitle handling | Resource intensive; no unlimited file sizes, arbitrary remote URLs or unbounded FFmpeg |
| Raster images | JPEG/JPG, PNG, WebP, AVIF, HEIC/HEIF, TIFF, BMP, GIF, ICO, APNG | Convert, resize, crop, rotate, compress, batch, strip/edit metadata, transparency, multi-page TIFF | HEIC/AVIF codec and patent licensing; animation/frame retention; EXIF orientation |
| Vector/design | SVG, PDF, EPS, PSD, XCF (where safely supported) | Preview/rasterize/export supported layers, inspect metadata | Avoid pretending full fidelity or arbitrary source-project editing; external renderer and licensing review |
| PDF | PDF | Merge, split, extract/reorder/delete/rotate pages, compress, watermark text, metadata, images/text extraction, OCR later | Encrypted PDFs, forms, signatures and OCR need separate safety and correctness review |
| Text/office | TXT, MD, HTML, RTF, DOCX, ODT, DOC, XLSX, XLS, ODS, CSV, TSV, PPTX, PPT, ODP | Read, convert, extract text, render PDF, merge where meaningful, batch | Office layout fidelity requires sandboxed renderer; macro-enabled formats rejected or handled as inert data |
| E-books | EPUB, MOBI, AZW3, FB2, HTML, TXT, PDF | Convert and extract metadata/cover when technically/legal supported | DRM-protected inputs not bypassed; PDF layout to reflow is lossy |
| Archives/compression | ZIP, 7Z, TAR, TAR.GZ/TGZ, GZ, BZ2, XZ, ZST, RAR (extract only if legal/supportable) | Inspect, safe extract, create supported formats, recompress | Strict path/symlink/bomb checks, encrypted archive policy, RAR write licensing |
| Structured data | JSON, XML, YAML, TOML, CSV, TSV, INI | Validate, pretty-print, convert supported schemas, compare, minify | XML entity expansion and parser attacks; avoid ambiguous schema conversion |
| Fonts | TTF, OTF, WOFF, WOFF2 | Inspect, convert compatible formats/subset if license allows | Respect embedding and redistribution rights |
| Other specialized | CAD, 3D, medical, executable, database, RAW camera | Research individually only after demand and safe parser review | No promise of universal conversion; no arbitrary code execution |

## Cross-media conversion matrix — priority feature

FileShape should expose **verified directional conversions across media families**, not only same-family codecs. Every operation must have explicit input/output constraints, resource caps and an accurate preview; the matrix below is **planned**, not shipped.

| Input | Output | Operation / user controls |
| --- | --- | --- |
| GIF / animated WebP / APNG | MP4, WebM | Preserve frame timing where possible; loop handling; choose resolution and codec |
| MP4 / MOV / MKV / WebM | GIF, animated WebP, APNG | Choose start/end, FPS, width/height, palette/quality and output size |
| MP4 / MOV / MKV / WebM | MP3, WAV, FLAC, M4A, OGG | Select existing audio track, optionally trim and choose output quality; no audio track → clear error |
| MP4 / MOV / MKV / WebM | JPG, PNG, WebP | Extract thumbnail at timestamp or selected frames |
| MP4 / MOV / MKV / WebM | ZIP of numbered images | Extract bounded frames at selected FPS/interval; strict file count and archive limits |
| Multiple JPG / PNG / WebP | GIF, animated WebP, APNG | User-ordered frames, per-frame delay, repeat count, canvas size |
| Multiple JPG / PNG / WebP | MP4, WebM | User-ordered slideshow with explicit duration, transitions only when supported |
| Audio + user-selected static image / solid-color background | MP4, WebM | Create video containing supplied audio; never imply a video can be inferred from audio alone |
| PDF | JPG, PNG, WebP, ZIP of pages | Render selected pages with bounded DPI, page count and pixel limits |
| JPG / PNG / WebP | PDF | Single or multi-image PDF, user-selected ordering |
| PDF | TXT, MD (where meaningful) | Extract embedded text; OCR separately opt-in and only with bounded language packs |
| EPUB | PDF | Render reflowable content with disclosed layout changes; reject DRM-protected inputs |
| Images / PDF | searchable PDF | Optional OCR, accuracy disclosure and privacy-safe local processing |
| Video | audio + optional cover image | Split streams into separate owned downloadable artifacts |
| Animated GIF | static PNG/JPG/WebP | Choose a specific frame, not arbitrary frame drop without notice |
| ZIP of images | PDF, GIF or MP4 | Strict archive inspection and user-confirmed order before transformation |

### Cross-media UX
- **Smart conversion suggestions:** after upload, show only supported transformations for the verified content type. Display format, expected quality loss, and relevant settings (time range, FPS, resolution, bitrate, page range).
- **Multi-output:** permit an owned result bundle (e.g. extracted audio plus preview frame) only when output quotas, size and storage have been explicitly validated.
- **Streaming and frame safety:** cap decoded pixels × frames, output bytes, FPS, duration, CPU, RAM, disk and subprocess time. Animated GIFs may be vastly larger than equivalent MP4; show estimated output size as an estimate, not a guarantee.
- **Audio/video compatibility:** stream-copy audio when the selected output container supports it; otherwise transcode with an explicit quality choice. Preserve variable GIF frame durations where possible and do not invent sound in silent sources.
- **Security:** no user-supplied FFmpeg filter expressions, protocols, remote URLs, external fonts or untrusted arbitrary command arguments. Use bounded fixed presets, owner isolation, atomic result delivery and temporary-file cleanup.
- **Priority:** implement GIF → MP4, video → GIF, video → audio and video → frame first; follow with image sequences → GIF/video, PDF → images and other cross-media operations after measured demand and load tests.

## Audio Studio — full metadata editor (first major expansion)

**Supported tag fields, where available in the container:** title, subtitle, artist, album artist, album, date (full ISO date where supported), year, original release date, genre, composer, lyricist, conductor, arranger, publisher, label, copyright, ISRC, BPM, key, language, track number / total, disc number / total, comment, description, encoder, URL, grouping, compilation flag, lyrics as plain metadata, custom fields and embedded cover art (add/replace/remove). Include explicit **clear field**, preserve unknown tags where possible and show unsupported fields as read-only or unavailable rather than silently discarding them.

- Format adapters: MP3 ID3v2.3/2.4; FLAC Vorbis comments and pictures; OGG/Opus Vorbis comments; MP4/M4A atoms; WAV/AIFF RIFF/ID3 where supported. Distinguish audio **streams** from metadata: avoid re-encoding when editing tags.
- Metadata safety: bounded string lengths, Unicode normalization, artwork MIME sniffing, dimension/byte/pixel limits, no external image URLs, safe temp file + atomic replacement, owner authorization, no path traversal, tag round-trip tests, lossless audio checksum verification where feasible.
- UI: tabs **Основное / Обложка / Дополнительно / Техническое**, single and batch edit, preserve/clear choices, before/after preview, export new file rather than mutating original uploads.
- Audio processing milestones: (1) inspect + tags, (2) trim + join, (3) video audio extraction, (4) split/gain/speed/normalization, (5) advanced batch and waveform if feasible. Do not add built-in music, promotional soundtracks or disallowed imagery.

## Shared capability registry contract

Each operation is a versioned server-authoritative entry with `operation_id`, input format/codec/container constraints, output format, file size, estimated CPU/memory/time/disk budget, accepted media MIME/magic, lossless/lossy semantics, max batch size, implementation adapter, tier policy, preview availability and deployment availability. Client UIs query authenticated capabilities; never infer permission from filename alone. Format detection uses safe bounded parsers and magic bytes, with extension only as a hint. Keep existing action IDs and API contracts backward compatible.

The processing system must reject unsafe inputs, archive bombs, malformed metadata, oversized media, unsupported codecs, symlinks and external network fetches. Isolate FFmpeg/office/vector/archive parsers with resource limits, timeouts, sandboxing and explicit dependency/license review. Preserve per-owner isolation, quotas, idempotent settlements, TTL cleanup, crash recovery, audit logs and halal-only project constraints in AGENTS.md.

## Priority and delivery sequence

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| P0 — Stabilize | Restore GitHub Actions, finish architecture 5.0 recovery and operational gates, test current bot/Mini App | Green final-head Python/Node/Docker CI, verified real Telegram E2E |
| P1 — Capability catalog | Server-driven format and action matrix, API/UI parity, honest unsupported-state UX | Versioned schema, contract tests, no regressions |
| P2 — Audio Studio metadata | Full metadata/tag read-write, cover art, supported format adapters, batch later | Round-trip metadata tests, unchanged audio when possible, safe artwork handling |
| P3 — Audio processing | Trim, concatenate, extract audio from video, split, gain and compression | FFmpeg format compatibility matrix, cleanup, bounded resource tests |
| P4 — PDF + images | Compress/split PDF, resize/crop/batch images, add modern formats where licensed | Fidelity, decompression safety, regression and resource tests |
| P5 — Office + archive | DOCX/ODT to PDF, spreadsheets/presentations where rendering is safe, 7Z/TAR family | Sandbox, layout review, path/bomb checks, dependency audits |
| P6 — Video | Selected video conversions and editing within measured capacity | Load/cost report, codec/stream tests, failure handling |
| P7 — Web/mobile | Shared API and entitlement parity, authenticated artifact download and history | Cross-platform E2E, migration, privacy and security review |
| P8 — Long-tail formats | E-books, vector, fonts, structured data and demand-driven specialist adapters | Explicit compatibility/licensing matrix and proven demand |

**Parallel track:** Telegram Stars PR #69 remains draft; enable only after verified checkout, refunds, quotas, real Telegram tests and owner approval. This document authorizes no new paid provider, hosting or purchases.

## Product completeness: one studio instead of many converters

**North star:** a user should complete the vast majority of common file workflows without needing a second conversion tool. This is a product goal, **not** a claim of universal compatibility. Measure top failed/unsupported intents and prioritize demand.

### Core studios and expansion backlog

1. **PDF Studio:** compress, merge, split, reorder, rotate, extract/delete pages, text/image extraction, safe text watermark, metadata, password handling for authorized files, forms, OCR and searchable PDF (later). Preserve digital signatures only when operation semantics allow; clearly warn when edits invalidate them.
2. **Image Studio:** resize/crop/rotate, format/quality conversion, EXIF inspect/remove, transparency, batch, animation frame selection, ICO generation, contact sheets, color profiles where supported.
3. **Audio Studio:** full metadata/tagging/cover art, trim, join, split, gain, normalize, playback speed, silence trimming, bitrate and channels, audio extraction from video; bounded batch editing.
4. **Video Studio:** trim, join compatible clips, compress, resize, transcode, rotate, mute, select/extract tracks, subtitles where supported, video ↔ animated GIF/WebP, thumbnails, frame extraction.
5. **Document Studio:** DOCX/ODT/TXT/RTF/HTML/MD/CSV/XLSX/PPTX/EPUB selected conversions, text extraction and safe previews. Do not claim full editable round-trip or pixel-perfect rendering.
6. **Archive Studio:** ZIP/7Z/TAR and supported compressed variants, list, selective extract, safe create/recompress, integrity checks; enforce archive bomb/path/symlink limits.
7. **Scan & OCR Studio:** camera capture in supported mobile clients, crop/perspective correction, text recognition, searchable PDF, offline/private options when feasible. Accuracy varies by script and image quality.
8. **Developer/Data Studio:** JSON/XML/YAML/TOML/CSV/TSV formatting, validation, bounded transformations, encoding conversions, Base64 and URL encoding; prevent XML entity expansion and malicious payload processing.
9. **Batch Workflow Studio:** multi-select, ordered input sets, per-item failure reports, bulk rename, preset actions, safe ZIP delivery, idempotent accounting. No hidden per-file charges.
10. **File Inspector & Privacy:** detect true file type, view supported metadata/technical details, strip EXIF and sensitive tags on explicit request, calculate checksums, compare files and report safe limits.

### Discoverability and retention
- **Upload-first UX:** detect file type, present only available actions and supported outputs; display exact unsupported reasons and alternatives.
- **Searchable tool catalog:** search by desired result (e.g., "extract audio") instead of requiring knowledge of codecs.
- **Favorites and recent operations:** optional, privacy-scoped; avoid persistent file storage by default.
- **Saved presets:** explicit format/quality/time-range preferences; do not store raw private content.
- **Cross-platform parity:** one capability source for bot, Mini App, web, Android and iOS; platform-specific transport and size limits must remain visible.
- **Measurement:** opt-in privacy-safe counts of requested tools, failure reasons, format popularity, processing latency and cost; no raw filenames or content in analytics.

### Delivery principle
Prefer **one end-to-end reliable workflow** over dozens of advertised but untested codecs. Release a small set of popular tools with real fixtures, load tests and supported transport, then expand the matrix iteratively. No third-party paid services or dependency licensing changes without owner approval.

## Definition of done for every format adapter
- Document exact input/output pair and limits; test invalid/malicious files, corruption, cancellation, restart and owner isolation.
- Prove output format, readable result, metadata preservation where promised, and no silent quality degradation claim.
- Verify resource budgets, concurrency, timeout, cleanup and sandbox isolation; add regression fixtures.
- Full Python tests, Mini App tests/build and Docker build pass on final PR head; then main CI passes after merge.
- Add UI labels only when functionality is merged **and** deployed; clearly distinguish design, code, deployment and user-visible readiness.

## One-week achievable scope (conditional)
Prioritize **P0 and P1**, then one tightly scoped **P2** metadata adapter if CI and real runtime checks are restored. Do not promise the entire format list, production-scale architecture, Stars billing and mobile stores within seven days.
