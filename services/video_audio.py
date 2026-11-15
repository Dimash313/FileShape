"""Extract only the audio stream from owner-supplied MP4/MOV video.

Domain-only utility: the caller owns private workspace, admission, quotas,
authorization and retention. No network protocols or bundled media assets.
"""

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from services.audio_tools import (
    MAX_AUDIO_OUTPUT_BYTES, MAX_DURATION_SECONDS, _pinned_audio_source,
    _program, probe_audio,
)

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov"})
VIDEO_DEMUXER = "mov,mp4,m4a,3gp,3g2,mj2"
MAX_VIDEO_INPUT_BYTES = 50 * 1024 * 1024
VIDEO_PROBE_TIMEOUT_SECONDS = 12
VIDEO_EXTRACT_TIMEOUT_SECONDS = 65


def _probe_pinned_video(pinned_path: str, fd: int) -> float:
    """Validate genuine video + audio within a self-contained MP4/MOV."""
    try:
        checked = subprocess.run(
            [
                _program("ffprobe"), "-v", "error",
                "-protocol_whitelist", "file,pipe",
                "-enable_drefs", "0", "-use_absolute_path", "0",
                "-show_entries", "format=format_name,duration:stream=codec_type",
                "-of", "json", pinned_path,
            ],
            capture_output=True, text=True, check=False,
            timeout=VIDEO_PROBE_TIMEOUT_SECONDS, pass_fds=(fd,),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Не удалось проверить видео за отведённое время") from None
    if checked.returncode:
        raise ValueError("Не удалось прочитать видеофайл")
    try:
        metadata = json.loads(checked.stdout)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("format"), dict):
            raise ValueError("Не удалось проверить дорожки и длительность видео")
        if not isinstance(metadata.get("streams"), list) or not all(
            isinstance(stream, dict) for stream in metadata["streams"]
        ):
            raise ValueError("Не удалось проверить дорожки и длительность видео")
        if metadata["format"].get("format_name") != VIDEO_DEMUXER:
            raise ValueError("Неподдерживаемый видеоконтейнер")
        kinds = {stream.get("codec_type") for stream in metadata["streams"]}
        if not {"video", "audio"} <= kinds:
            raise ValueError("Видео должно содержать видеоряд и аудиодорожку")
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_SECONDS:
            raise ValueError("Длительность видео должна быть не более 10 минут")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and str(error) in (
            "Неподдерживаемый видеоконтейнер",
            "Видео должно содержать видеоряд и аудиодорожку",
            "Длительность видео должна быть не более 10 минут",
        ):
            raise
        raise ValueError("Не удалось проверить дорожки и длительность видео") from None
    return duration


def extract_audio_from_video(source: Path, target: Path) -> dict:
    """Convert a genuine MP4/MOV video's first audio stream to MP3 at 128k.

    Source must be a regular file in the caller's private temporary workspace.
    The destination must be absent. Only a validated, complete result becomes
    visible; failures cannot overwrite or publish partial results.
    """
    if not isinstance(source, Path) or source.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Поддерживаются видео MP4 и MOV")
    if not isinstance(target, Path) or target.suffix.lower() != ".mp3":
        raise ValueError("Результат извлечения должен быть MP3")
    if target.exists() or target.is_symlink():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог результата")

    with _pinned_audio_source(source) as (pinned_path, input_fd):
        # _pinned_audio_source pins a no-follow regular inode; unlike
        # probe_audio, it allows MP4 headers so a video can be inspected.
        if os.pread(input_fd, 8, 0)[4:8] != b"ftyp":
            raise ValueError("Неподдерживаемый видеоконтейнер")
        size = os.fstat(input_fd).st_size
        if not 0 < size <= MAX_VIDEO_INPUT_BYTES:
            raise ValueError("Видеофайл превышает 50 МиБ")
        original_seconds = _probe_pinned_video(pinned_path, input_fd)

        handle, scratch_name = tempfile.mkstemp(
            prefix=".fileshape-video-audio-", suffix=".mp3", dir=target.parent
        )
        os.close(handle)
        scratch = Path(scratch_name)
        try:
            command = [
                _program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel",
                "error", "-y", "-threads", "1",
                "-protocol_whitelist", "file,pipe",
                "-enable_drefs", "0", "-use_absolute_path", "0",
                "-i", pinned_path,
                "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-map_chapters", "-1",
                "-c:a", "libmp3lame", "-b:a", "128k",
                "-ar", "48000", "-ac", "2",
                "-t", str(MAX_DURATION_SECONDS), "-fs",
                str(MAX_AUDIO_OUTPUT_BYTES), str(scratch),
            ]
            try:
                outcome = subprocess.run(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False,
                    timeout=VIDEO_EXTRACT_TIMEOUT_SECONDS, pass_fds=(input_fd,),
                )
            except subprocess.TimeoutExpired:
                raise ValueError("Извлечение аудио превысило лимит времени") from None
            if outcome.returncode != 0 or not scratch.is_file():
                raise ValueError("Не удалось извлечь аудио из видео")
            if not 0 < scratch.stat().st_size <= MAX_AUDIO_OUTPUT_BYTES:
                raise ValueError("Аудиорезультат пустой или слишком большой")

            audio = probe_audio(scratch)
            if audio["codec"] != "mp3":
                raise ValueError("Неверный формат извлечённого аудио")
            if float(audio["seconds"]) > original_seconds + 0.5:
                raise ValueError("Длительность аудиорезультата недопустима")
            scratch.chmod(0o600)
            try:
                os.link(scratch, target)
            except FileExistsError:
                raise ValueError("Файл результата уже существует") from None
            return {
                "seconds": audio["seconds"],
                "codec": "mp3",
                "source_seconds": round(original_seconds, 1),
            }
        finally:
            scratch.unlink(missing_ok=True)
