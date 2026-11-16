"""Bounded animated GIF export from an owner's MP4/MOV file.

Domain only. The caller supplies an isolated private temporary workspace,
enforces authorization and quota, and removes the output after delivery.
No URLs, external MOV data references, or bundled video/image content.
"""

import json
import math
import os
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from services.audio_tools import _pinned_audio_source, _program
from services.video_audio import VIDEO_DEMUXER, VIDEO_EXTENSIONS

MAX_GIF_SOURCE_BYTES = 20 * 1024 * 1024
MAX_GIF_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_GIF_SECONDS = 8
MAX_GIF_INPUT_EDGE = 1920
MAX_GIF_INPUT_PIXELS = 1920 * 1080
MAX_GIF_INPUT_FPS = 60
GIF_MAX_EDGE = 320
GIF_EXPORT_FPS = 8
GIF_MAX_FRAMES = MAX_GIF_SECONDS * GIF_EXPORT_FPS
GIF_PROBE_TIMEOUT_SECONDS = 12
GIF_ENCODE_TIMEOUT_SECONDS = 45


def _parse_fps(raw: object) -> float:
    """Fail closed for unknown and implausible source frame rates."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 32:
        raise ValueError("Недопустимая частота кадров видео")
    try:
        rate = float(Fraction(raw))
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ValueError("Недопустимая частота кадров видео") from None
    if not math.isfinite(rate) or not 0 < rate <= MAX_GIF_INPUT_FPS:
        raise ValueError("Частота кадров видео превышает лимит 60 FPS")
    return rate


def _probe_gif_video(pinned_path: str, fd: int) -> dict:
    """Inspect video from the same already validated and open inode."""
    command = [
        _program("ffprobe"), "-v", "error",
        "-protocol_whitelist", "file,pipe",
        "-enable_drefs", "0", "-use_absolute_path", "0",
        "-select_streams", "v:0",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,width,height,avg_frame_rate"
        ":stream_disposition=attached_pic",
        "-of", "json", pinned_path,
    ]
    try:
        checked = subprocess.run(
            command, capture_output=True, text=True,
            timeout=GIF_PROBE_TIMEOUT_SECONDS, check=False, pass_fds=(fd,),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Время проверки видео истекло") from None
    if checked.returncode != 0 or len(checked.stdout) > 64_000:
        raise ValueError("Не удалось прочитать видео")
    try:
        metadata = json.loads(checked.stdout)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("format"), dict):
            raise ValueError("Не удалось проверить видео")
        if metadata["format"].get("format_name") != VIDEO_DEMUXER:
            raise ValueError("Неподдерживаемый видеоконтейнер")
        streams = metadata.get("streams")
        if not isinstance(streams, list) or len(streams) != 1:
            raise ValueError("Нужна одна основная видеодорожка")
        stream = streams[0]
        if not isinstance(stream, dict) or stream.get("codec_type") != "video":
            raise ValueError("Нужна видеодорожка")
        if not isinstance(stream.get("disposition"), dict) or (
            stream["disposition"].get("attached_pic") != 0
        ):
            raise ValueError("Обложка не является видеорядом")
        width, height = stream.get("width"), stream.get("height")
        if any(type(dimension) is not int for dimension in (width, height)):
            raise ValueError("Не удалось определить разрешение видео")
        if not (0 < width <= MAX_GIF_INPUT_EDGE
                and 0 < height <= MAX_GIF_INPUT_EDGE
                and width * height <= MAX_GIF_INPUT_PIXELS):
            raise ValueError("Разрешение видео превышает лимит")
        rate = _parse_fps(stream.get("avg_frame_rate"))
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= MAX_GIF_SECONDS:
            raise ValueError("Длительность GIF не более 8 секунд")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, ValueError) and str(exc) in {
            "Неподдерживаемый видеоконтейнер",
            "Нужна одна основная видеодорожка",
            "Нужна видеодорожка",
            "Обложка не является видеорядом",
            "Не удалось определить разрешение видео",
            "Разрешение видео превышает лимит",
            "Недопустимая частота кадров видео",
            "Частота кадров видео превышает лимит 60 FPS",
            "Длительность GIF не более 8 секунд",
        }:
            raise
        raise ValueError("Не удалось проверить видео") from None
    return {"source_seconds": duration, "source_width": width,
            "source_height": height, "source_fps": rate}


def _validate_gif(path: Path, *, source_seconds: float) -> dict:
    """Decode every small bounded frame before making output public."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Результат GIF недоступен")
    if not 0 < path.stat().st_size <= MAX_GIF_OUTPUT_BYTES:
        raise ValueError("Результат GIF пустой или превышает 8 МиБ")
    try:
        with Image.open(path) as frames:
            if frames.format != "GIF":
                raise ValueError("Неверный формат GIF")
            width, height = frames.size
            if not (0 < width <= GIF_MAX_EDGE and 0 < height <= GIF_MAX_EDGE):
                raise ValueError("Недопустимые размеры GIF")
            total = frames.n_frames
            if not 2 <= total <= GIF_MAX_FRAMES:
                raise ValueError("Недопустимое количество кадров GIF")
            duration_ms = 0
            for frame_no in range(total):
                frames.seek(frame_no)
                duration_ms += int(frames.info.get("duration", 0))
                frames.load()
            if not 0 < duration_ms <= (MAX_GIF_SECONDS + 1) * 1000:
                raise ValueError("Недопустимая длительность GIF")
            if duration_ms / 1000 > source_seconds + 0.5:
                raise ValueError("GIF длиннее исходного видео")
            return {"width": width, "height": height, "frames": total,
                    "seconds": round(duration_ms / 1000, 2)}
    except (OSError, UnidentifiedImageError, EOFError, TypeError, OverflowError):
        raise ValueError("Не удалось проверить GIF") from None


def video_to_gif(source: Path, target: Path) -> dict:
    """Convert at most 8 s of a pinned MP4/MOV to a private animated GIF.

    The result is installed atomically without overwriting an existing path.
    No user-supplied FFmpeg flags, URLs, metadata or extra input files.
    """
    if not isinstance(source, Path) or source.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Поддерживаются только MP4 и MOV")
    if not isinstance(target, Path) or target.suffix.lower() != ".gif":
        raise ValueError("Формат результата должен быть GIF")
    if target.exists() or target.is_symlink():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог результата")

    with _pinned_audio_source(source) as (pinned_path, source_fd):
        if os.pread(source_fd, 8, 0)[4:8] != b"ftyp":
            raise ValueError("Неподдерживаемый видеоконтейнер")
        if os.fstat(source_fd).st_size > MAX_GIF_SOURCE_BYTES:
            raise ValueError("Исходное видео превышает 20 МиБ")
        details = _probe_gif_video(pinned_path, source_fd)

        descriptor, filename = tempfile.mkstemp(
            prefix=".fileshape-video-gif-", suffix=".gif", dir=target.parent
        )
        os.close(descriptor)
        stage = Path(filename)
        try:
            command = [
                _program("ffmpeg"), "-nostdin", "-hide_banner",
                "-loglevel", "error", "-y", "-threads", "1",
                "-filter_threads", "1",
                "-protocol_whitelist", "file,pipe",
                "-enable_drefs", "0", "-use_absolute_path", "0",
                "-i", pinned_path,
                "-map", "0:v:0", "-an", "-sn", "-dn",
                "-map_metadata", "-1", "-map_chapters", "-1",
                "-vf",
                "fps=8,scale=w='min(320,iw)':h='min(320,ih)'"
                ":force_original_aspect_ratio=decrease:flags=bicubic,format=rgb8",
                "-frames:v", str(GIF_MAX_FRAMES),
                "-t", str(MAX_GIF_SECONDS),
                "-fs", str(MAX_GIF_OUTPUT_BYTES),
                "-loop", "0", "-f", "gif", str(stage),
            ]
            try:
                output = subprocess.run(
                    command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=GIF_ENCODE_TIMEOUT_SECONDS, check=False,
                    pass_fds=(source_fd,),
                )
            except subprocess.TimeoutExpired:
                raise ValueError("Создание GIF превысило лимит времени") from None
            if output.returncode != 0:
                raise ValueError("Не удалось создать GIF из видео")
            verified = _validate_gif(stage, source_seconds=details["source_seconds"])
            stage.chmod(0o600)
            try:
                os.link(stage, target)
            except FileExistsError:
                raise ValueError("Файл результата уже существует") from None
            return {**verified, "source_seconds": round(details["source_seconds"], 2)}
        finally:
            stage.unlink(missing_ok=True)
