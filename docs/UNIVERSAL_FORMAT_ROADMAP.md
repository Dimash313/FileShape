# FileShape — Universal Format & Editor Roadmap
Status: **product proposal, not implemented or deployed**. Created 2026-11-15. This supplements [ROADMAP.md](ROADMAP.md) and [ARCHITECTURE_5.md](ARCHITECTURE_5.md); it does not change approved Free/Pro pricing, quotas, privacy, security, billing or release gates.

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

## Definition of done for every format adapter
- Document exact input/output pair and limits; test invalid/malicious files, corruption, cancellation, restart and owner isolation.
- Prove output format, readable result, metadata preservation where promised, and no silent quality degradation claim.
- Verify resource budgets, concurrency, timeout, cleanup and sandbox isolation; add regression fixtures.
- Full Python tests, Mini App tests/build and Docker build pass on final PR head; then main CI passes after merge.
- Add UI labels only when functionality is merged **and** deployed; clearly distinguish design, code, deployment and user-visible readiness.

## One-week achievable scope (conditional)
Prioritize **P0 and P1**, then one tightly scoped **P2** metadata adapter if CI and real runtime checks are restored. Do not promise the entire format list, production-scale architecture, Stars billing and mobile stores within seven days.
