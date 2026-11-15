"""Bounded MP3 concatenation of 2–5 owner-workspace audio recordings.

Domain-only processing. The caller owns authentication, quota accounting and
lifecycle of its private temporary workspace. No media content is bundled.
All sources stay pinned to validated file descriptors across probe + FFmpeg.
"""

import os
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

from services.audio_tools import (
    MAX_AUDIO_OUTPUT_BYTES, MAX_DURATION_SECONDS, _pinned_audio_source,
    _probe_pinned_audio, _program, probe_audio,
)

MAX_JOIN_INPUTS = 5
MAX_JOIN_FILE_BYTES = 20 * 1024 * 1024
MAX_JOIN_TOTAL_BYTES = 50 * 1024 * 1024
JOIN_TIMEOUT_SECONDS = 65


def join_audio(sources: Sequence[Path], target: Path) -> dict:
    """Concatenate recordings in the supplied order into an MP3 at 128 kbit/s.

    The destination must not already exist; no partial results are published.
    Source limits: 2–5 files, up to 20 MiB each, 50 MiB total, 600 s total.
    """
    if not isinstance(sources, (tuple, list)) or not 2 <= len(sources) <= MAX_JOIN_INPUTS:
        raise ValueError("Для склеивания нужны от 2 до 5 аудиофайлов")
    if not isinstance(target, Path) or target.suffix.lower() != ".mp3":
        raise ValueError("Результат склеивания должен быть MP3")
    if target.is_symlink() or target.exists():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог для результата")

    # Every file is opened once with O_NOFOLLOW by the shared audio guard.
    # fstat and FFprobe inspect *that same inode*, even if the original path
    # is renamed or replaced while the operation is running. ExitStack keeps
    # all descriptors open until FFmpeg finishes, and closes them on failure.
    with ExitStack() as opened:
        pinned_paths = []
        descriptors = []
        total_bytes = 0
        total_seconds = 0.0
        for source in sources:
            if not isinstance(source, Path):
                raise ValueError("Некорректный путь к аудиофайлу")
            pinned_path, fd = opened.enter_context(_pinned_audio_source(source))
            size = os.fstat(fd).st_size
            if not 0 < size <= MAX_JOIN_FILE_BYTES:
                raise ValueError("Аудиофайл недопустим или превышает 20 МиБ")
            total_bytes += size
            if total_bytes > MAX_JOIN_TOTAL_BYTES:
                raise ValueError("Суммарный размер аудиофайлов превышает 50 МиБ")
            # Exact seconds avoid rounding 300.04 + 300.04 down to 600.0.
            info = _probe_pinned_audio(pinned_path, fd, exact=True)
            total_seconds += float(info["seconds"])
            if total_seconds > MAX_DURATION_SECONDS:
                raise ValueError("Общая длительность аудио должна быть не более 10 минут")
            pinned_paths.append(pinned_path)
            descriptors.append(fd)

        fd, scratch = tempfile.mkstemp(
            prefix=".fileshape-audio-join-", suffix=".mp3", dir=target.parent
        )
        os.close(fd)
        temp_path = Path(scratch)
        try:
            filters = [
                f"[{i}:a:0]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
                for i in range(len(pinned_paths))
            ]
            streams = "".join(f"[a{i}]" for i in range(len(pinned_paths)))
            filters.append(
                f"{streams}concat=n={len(pinned_paths)}:v=0:a=1[joined]"
            )
            command = [
                _program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel",
                "error", "-y", "-threads", "1", "-filter_complex_threads", "1",
            ]
            for source in pinned_paths:
                command.extend(["-protocol_whitelist", "file,pipe", "-i", source])
            command.extend([
                "-filter_complex", ";".join(filters), "-map", "[joined]",
                "-vn", "-sn", "-dn", "-map_metadata", "-1",
                "-map_chapters", "-1", "-c:a", "libmp3lame",
                "-b:a", "128k", "-ar", "48000", "-ac", "2",
                "-t", str(MAX_DURATION_SECONDS), "-fs",
                str(MAX_AUDIO_OUTPUT_BYTES), str(temp_path),
            ])
            try:
                result = subprocess.run(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=False, timeout=JOIN_TIMEOUT_SECONDS,
                    pass_fds=tuple(descriptors),
                )
            except subprocess.TimeoutExpired:
                raise ValueError("Склеивание аудио превысило лимит времени") from None
            if result.returncode != 0 or not temp_path.is_file():
                raise ValueError("Не удалось склеить аудиофайлы")
            if not 0 < temp_path.stat().st_size <= MAX_AUDIO_OUTPUT_BYTES:
                raise ValueError("Результат склеивания превысил допустимый размер")
            result_info = probe_audio(temp_path)
            if abs(float(result_info["seconds"]) - total_seconds) > 1.0:
                raise ValueError("Не удалось проверить длительность результата")
            temp_path.chmod(0o600)
            try:
                os.link(temp_path, target)
            except FileExistsError:
                raise ValueError("Файл результата уже существует") from None
            return {
                "seconds": result_info["seconds"], "codec": result_info["codec"],
                "inputs": len(pinned_paths),
            }
        finally:
            temp_path.unlink(missing_ok=True)
