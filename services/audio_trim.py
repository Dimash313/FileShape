"""Bounded, user-requested Telegram audio trimming.

No sample recordings or generated soundtrack; operates only on uploaded audio.
The bot stores source/results in a temporary service-owned directory, while
this helper verifies the actual stream with ffprobe and runs bounded FFmpeg.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

from services.audio_tools import (
    AUDIO_EXTENSIONS, MAX_AUDIO_OUTPUT_BYTES, MAX_DURATION_SECONDS,
    _program, probe_audio,
)

MAX_AUDIO_INPUT_BYTES = 20 * 1024 * 1024
MAX_TRIM_SPEC_LENGTH = 40
_RANGE_RE = re.compile(
    r"([0-9]{2}):([0-5][0-9]):([0-5][0-9]) *- *"
    r"([0-9]{2}):([0-5][0-9]):([0-5][0-9])"
)


def parse_trim_range(spec: str) -> tuple[int, int]:
    """Strict HH:MM:SS-HH:MM:SS, integer seconds within 10 minutes."""
    if not isinstance(spec, str) or len(spec) > MAX_TRIM_SPEC_LENGTH:
        raise ValueError("Укажи начало и конец: 00:00:05-00:00:20")
    match = _RANGE_RE.fullmatch(spec.strip())
    if match is None:
        raise ValueError("Используй формат 00:00:05-00:00:20")
    start_h, start_m, start_s, end_h, end_m, end_s = map(int, match.groups())
    start = start_h * 3600 + start_m * 60 + start_s
    end = end_h * 3600 + end_m * 60 + end_s
    if not 0 <= start < end <= MAX_DURATION_SECONDS:
        raise ValueError("Начало должно быть раньше конца, а конец — не более 10 минут")
    return start, end


def trim_audio(source: Path, target: Path, spec: str) -> dict:
    """Accurate decoded trim to MP3 128k; verified bounds and safe cleanup.

    Input/output paths must come from the server's own temporary directory.
    Never accept a client URL, command, filename or option as FFmpeg flags.
    """
    start, end = parse_trim_range(spec)
    if (
        source.suffix.lower() not in AUDIO_EXTENSIONS
        or target.suffix.lower() != ".mp3"
        or source.resolve() == target.resolve()
    ):
        raise ValueError("Неподдерживаемый путь или формат аудио")
    if (
        source.is_symlink() or not source.is_file()
        or not 0 < source.stat().st_size <= MAX_AUDIO_INPUT_BYTES
    ):
        raise ValueError("Аудиофайл отсутствует или превышает лимит 20 МБ")

    # probe_audio rejects any video track and input duration > 10 min.
    # exact=True avoids rounding up the source duration when checking the end.
    input_info = probe_audio(source, exact=True)
    if end > input_info["seconds"]:
        raise ValueError("Конец отрезка выходит за длительность аудиофайла")

    # Output is MP3 intentionally: codec/container behavior is predictable
    # for Telegram voice/FLAC/WAV/M4A sources, with no stream-copy seek drift.
    command = [
        _program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-protocol_whitelist", "file,pipe", "-i", str(source),
        "-ss", str(start), "-t", str(end - start),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-fs", str(MAX_AUDIO_OUTPUT_BYTES), str(target),
    ]
    success = False
    try:
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=65, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("Обрезка аудио превысила лимит времени") from None
        if result.returncode != 0 or not target.is_file():
            raise ValueError("Не удалось обрезать запись")
        if not 0 < target.stat().st_size <= MAX_AUDIO_OUTPUT_BYTES:
            raise ValueError("Результат обрезки пустой или слишком большой")
        actual = probe_audio(target, exact=True)["seconds"]
        if not 0 < actual <= end - start + 0.35:
            raise ValueError("Не удалось подтвердить длительность результата")
        success = True
        return {
            "start_seconds": start,
            "end_seconds": end,
            "actual_seconds": round(actual, 2),
            "output_format": "mp3",
        }
    finally:
        if not success:
            target.unlink(missing_ok=True)
