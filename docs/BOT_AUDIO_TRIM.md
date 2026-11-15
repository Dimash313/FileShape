# FileShape 5.0.12 — Telegram audio trim (draft)

**Status:** implemented in an isolated PR branch, **not merged, deployed or
available in the current bot**. This is a small bot-only slice of the planned
Audio Studio, not the full editor, metadata/tagging, joining, or video-audio
extraction release.

## User flow

- Send an audio document (MP3/WAV/OGG/OGA/M4A/FLAC), Telegram audio or voice
  note in a **private chat**, with a reported size between 1 byte and 20 MiB.
- Press `✂️ Обрезать запись`, then reply with a strict integer-second range
  `HH:MM:SS-HH:MM:SS`, for example `00:00:05-00:00:20`.
- The bot validates the timestamp syntax **before** reserving a metered
  conversion. No client-provided path, filename or FFmpeg flags are executed.
- After owner/access and quota authorization, the bot downloads the original
  audio to a service-owned temporary folder, rechecks its size, validates
  audio-only streams and precise duration with ffprobe, and encodes the
  selected part to **MP3 128 kbps** using a bounded FFmpeg process.
- Successful Telegram document delivery consumes **one** FileShape operation,
  not one per second; parser/download, conversion and delivery failures use
  the existing bot operation release flow. The result has the usual file
  follow-up menu if <=20 MiB. `/cancel` clears the pending timestamp form.
- No audio bytes or filenames are persisted in the quota ledger, and all
  temporary files are removed after the request.

## Security and accuracy

- `HH:MM:SS` values are strict ASCII digits. Start must be nonnegative,
  less than end, and end must be <=10 minutes and <=the actual input
  duration. The minimum segment is one whole second. This first increment
  does not provide millisecond-precision waveforms or a timeline UI.
- Sources with video tracks or unsupported containers are rejected. Client
  files must meet the existing 20 MiB Telegram Bot API download ceiling;
  a successful probe still does not guarantee decoding every unusual file.
- FFmpeg uses a fixed binary, trusted temporary paths, restricted protocols,
  no attached cover/video/subtitles/data streams, no inherited metadata,
  process timeout, and output byte cap. Re-encoding introduces MP3 quality
  loss and possible encoder padding; the exported duration is reprobed and
  must be within a bounded tolerance.
- Source and result bytes are held temporarily in the existing bot process,
  not in the proposed new durable job/blob prototype. No native or
  HTTP/Mini App route is added; the existing `api/conversion_catalog.py`
  remains an honest list of *HTTP* server capabilities.
- Tests cover syntax injection/invalid ranges, actual generated WAV -> MP3
  trimming, duration checks, source format mismatch, symlink refusal,
  Telegram owner-scoped FSM, no-quota-before-valid-input, and normal
  delivery. FFmpeg and ffprobe are required on the deployed host.

## Release gate / rollback

1. Resolve GitHub Actions job dispatch and obtain exact-head Python tests,
   Mini App Node tests/TypeScript build, and Docker build. GitHub failures
   that occur before runner assignment are not evidence of passing code.
2. Review real private-chat flow, Telegram voice/audio, incorrect format,
   malformed input, cancellation, quota depletion, retries, and result
   delivery failures on the actual bot with a test user. Do not turn on
   billing as part of this change.
3. Merge only when green, then verify post-merge main CI and a controlled
   bot deploy. Rollback is a code revert to the previous action menu and
   handler; no persistent storage migration is required.

## Halal policy

No audio samples, music, content recommendations or promotional music are
packaged; the service is a neutral, general-purpose editor of user-supplied
recordings. No images of living beings, advertisements, external APIs, payment
providers, new dependencies or paid features. Mandatory `AGENTS.md` rules
remain applicable.
