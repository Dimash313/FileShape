"""Bounded concatenation of server-local, user-supplied audio recordings.

Domain-only utility: no Telegram, HTTP, database or quota decisions live here.
The caller owns the private workspace and removes final outputs after delivery.
"""

import os
import stat
import subprocess
import tempfile
from pathlib import Path
from collections.abc import Sequence

from services.audio_tools import MAX_AUDIO_OUTPUT_BYTES, MAX_DURATION_SECONDS, probe_audio, _program

MAX_JOIN_INPUTS = 5
MAX_JOIN_FILE_BYTES = 20 * 1024 * 1024
MAX_JOIN_TOTAL_BYTES = 50 * 1024 * 1024
JOIN_TIMEOUT_SECONDS = 65


def _regular_file(path: Path) -> Path:
    """Reject symlinks, directories, missing files and oversized inputs."""
    try:
        details = path.lstat()
    except OSError:
        raise ValueError("Не удалось прочитать аудиофайл") from None
    if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= MAX_JOIN_FILE_BYTES:
        raise ValueError("Аудиофайл недопустим или превышает 20 МиБ")
    return path.resolve(strict=True)


def join_audio(sources: Sequence[Path], target: Path) -> dict:
    """Join 2–5 recordings in the supplied order, exporting MP3 at 128 kbit/s.

    The destination must not exist. A private intermediate file is atomically
    linked into place only after validation, so failed jobs cannot publish a
    partial final result. Audio durations are capped at ten minutes total.
    """
    if not isinstance(sources, (tuple, list)) or not 2 <= len(sources) <= MAX_JOIN_INPUTS:
        raise ValueError("Для склеивания нужны от 2 до 5 аудиофайлов")
    if not isinstance(target, Path) or target.suffix.lower() != ".mp3":
        raise ValueError("Результат склеивания должен быть MP3")
    if target.is_symlink() or target.exists():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог для результата")

    resolved = []
    total_bytes = 0
    total_seconds = 0.0
    for source in sources:
        if not isinstance(source, Path):
            raise ValueError("Некорректный путь к аудиофайлу")
        safe_path = _regular_file(source)
        total_bytes += safe_path.stat().st_size
        if total_bytes > MAX_JOIN_TOTAL_BYTES:
            raise ValueError("Суммарный размер аудиофайлов превышает 50 МиБ")
        info = probe_audio(safe_path)
        total_seconds += float(info["seconds"])
        if total_seconds > MAX_DURATION_SECONDS:
            raise ValueError("Общая длительность аудио должна быть не более 10 минут")
        resolved.append(safe_path)

    fd, scratch = tempfile.mkstemp(prefix=".fileshape-audio-join-", suffix=".mp3", dir=target.parent)
    os.close(fd)
    temp_path = Path(scratch)
    try:
        graph = []
        for index in range(len(resolved)):
            graph.append(f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]")
        joined_inputs = "".join(f"[a{index}]" for index in range(len(resolved)))
        graph.append(f"{joined_inputs}concat=n={len(resolved)}:v=0:a=1[joined]")
        command = [_program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-y", "-threads", "1", "-filter_complex_threads", "1"]
        for source in resolved:
            command.extend(["-protocol_whitelist", "file,pipe", "-i", str(source)])
        command.extend(["-filter_complex", ";".join(graph), "-map", "[joined]",
                        "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
                        "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                        "-t", str(MAX_DURATION_SECONDS), "-fs", str(MAX_AUDIO_OUTPUT_BYTES),
                        str(temp_path)])
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    check=False, timeout=JOIN_TIMEOUT_SECONDS)
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
        return {"seconds": result_info["seconds"], "codec": result_info["codec"],
                "inputs": len(resolved)}
    finally:
        temp_path.unlink(missing_ok=True)
