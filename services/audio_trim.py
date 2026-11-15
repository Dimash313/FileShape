"""Bounded, user-requested Telegram audio trimming.

No sample recordings or generated soundtrack; operates only on uploaded audio.
The bot stores source/results in a temporary service-owned directory, while
this helper verifies the actual stream with ffprobe and runs bounded FFmpeg.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import tempfile

from services.audio_tools import (
    AUDIO_EXTENSIONS, MAX_AUDIO_OUTPUT_BYTES, MAX_DURATION_SECONDS,
    _pinned_audio_source, _probe_pinned_audio, _program, probe_audio,
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
    """Accurate MP3 trim using one validated, pinned input file descriptor.

    Sources and destinations must live in the calling service's private
    workspace. Never use a URL, client-provided flags or filename as FFmpeg
    options. Failed jobs cannot overwrite or leave a partial final result.
    """
    start, end = parse_trim_range(spec)
    if (
        source.suffix.lower() not in AUDIO_EXTENSIONS
        or target.suffix.lower() != ".mp3"
        or source.resolve() == target.resolve()
    ):
        raise ValueError("Неподдерживаемый путь или формат аудио")
    if target.exists() or target.is_symlink():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог результата")

    # Opening once prevents a path substitution between validation and the
    # native tools. fstat verifies the size of exactly the inode FFmpeg sees.
    with _pinned_audio_source(source) as (pinned_path, fd):
        if not 0 < os.fstat(fd).st_size <= MAX_AUDIO_INPUT_BYTES:
            raise ValueError("Аудиофайл отсутствует или превышает лимит 20 МБ")

        input_info = _probe_pinned_audio(pinned_path, fd, exact=True)
        if end > input_info["seconds"]:
            raise ValueError("Конец отрезка выходит за длительность аудиофайла")

        # Encode inside the target directory. A hard-link installs the final
        # result only if its name still does not exist. The scratch file is
        # always unlinked, whether conversion, validation or linking fails.
        handle, scratch_name = tempfile.mkstemp(
            prefix=".fileshape-audio-trim-", suffix=".mp3", dir=target.parent
        )
        os.close(handle)
        scratch = Path(scratch_name)
        try:
            command = [
                _program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-i", pinned_path,
                "-ss", str(start), "-t", str(end - start),
                "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-map_chapters", "-1",
                "-c:a", "libmp3lame", "-b:a", "128k",
                "-fs", str(MAX_AUDIO_OUTPUT_BYTES), str(scratch),
            ]
            try:
                result = subprocess.run(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=65, check=False, pass_fds=(fd,),
                )
            except subprocess.TimeoutExpired:
                raise ValueError("Обрезка аудио превысила лимит времени") from None
            if result.returncode != 0 or not scratch.is_file():
                raise ValueError("Не удалось обрезать запись")
            if not 0 < scratch.stat().st_size <= MAX_AUDIO_OUTPUT_BYTES:
                raise ValueError("Результат обрезки пустой или слишком большой")
            actual = probe_audio(scratch, exact=True)["seconds"]
            if not 0 < actual <= end - start + 0.35:
                raise ValueError("Не удалось подтвердить длительность результата")
            scratch.chmod(0o600)
            try:
                os.link(scratch, target)
            except FileExistsError:
                raise ValueError("Файл результата уже существует") from None
            return {
                "start_seconds": start,
                "end_seconds": end,
                "actual_seconds": round(actual, 2),
                "output_format": "mp3",
            }
        finally:
            scratch.unlink(missing_ok=True)
