# FileShape 5.0.13 — MP3 metadata editor (bot-only, draft)

**Status:** code in a stacked draft PR, **not merged, deployed or verified
through full GitHub CI**. Depends on PR #89 (Telegram audio trim) because it
extends the same private-chat audio file action navigation.

## Available in the proposed bot build

After uploading an **MP3** of at most **20 MiB** and 10 minutes, choose
`🏷 Теги MP3` and send one text message:

```text
Название | Исполнитель | Альбом | Год | Жанр
```

Example using non-musical general-purpose recording metadata:

```text
Урок | Автор | Сборник | 2026 | Образование
```

Five fields are required in that exact order. `-` means **keep existing tag**,
`~` means **remove existing tag**, and at least one field must be changed.
Title, artist, album, year/date and genre are supported. Year is exactly four
ASCII digits. Each text value is at most 120 characters; control characters,
NUL, newlines, and overlong input are rejected **before** quota reservation.
The separator character `|` is not supported inside field values.

This stage supports **MP3 only**, not M4A, FLAC, OGG, WAV or MP3 cover
replacement. The existing embedded **JPEG/PNG** attached picture (if any)
is copied without recoding along with the original MP3 audio stream. Unknown
video streams or more than one artwork stream are rejected rather than
silently discarded. A later distinct scope may add image upload/replace/remove,
while respecting project-wide restrictions and user-submitted media privacy.

## Security, honesty and accounting

- Telegram button/owner chat checks, file-id provenance and FSM are the same
  as the existing bot actions; stored state includes a Telegram file ID and
  owner ID but no permanent audio bytes, paths or metadata.
- Input is downloaded to a service-owned temporary directory; every output
  is temporary and deleted after processing/delivery. Do not log user tags.
- FFprobe validates the MP3 container, codec, duration, number/type of
  streams and optional artwork. FFmpeg is invoked as a fixed argument list
  with `-nostdin`, restricted file/pipe protocols, `-c copy` and caps on
  subprocess time/output size. **No shell or user-controlled paths**.
- The output is re-probed to confirm edited tags, retained audio codec and
  presence of any existing cover. A failed output is deleted; the source
  recording is never edited in place.
- Validating text does **not** consume a quota operation. A successful
  Telegram document delivery consumes **one** operation via the existing
  signed bot-to-API quota bridge. Download, FFmpeg or delivery failures
  release the reservation. This PR does not edit the metering service.
- Existing Telegram Bot API 20 MiB input cap remains. The whole app cannot
  be claimed to support 100 MiB upload, generic ID3v2 frames, or every audio
  format.

## Validation / rollout

Locally, the FFmpeg technique was checked with a generated **silent** MP3
and a plain geometric attached PNG: writing/clearing tags works and the
existing cover survives. These are narrow tool-level checks, **not** a
successful repository-wide build or end-to-end Telegram test.

Added tests exercise malformed/injected metadata, content/symlink/path
failures, real MP3 metadata round trips, preserved cover, owner isolation,
validation-before-quota, and one metered delivery. They require green final
head Python tests, Node/Mini App TypeScript build, Docker build, review of
the parent PR, post-merge main CI and manual Telegram testing before release.

**Rollback:** revert this feature branch/PR; do not change the running bot.
No migrations, payments, paid providers, content, audio samples, music,
third-party services, user imagery, advertising or new dependencies have
been added. `AGENTS.md` applies to all follow-up features.
