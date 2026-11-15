"""Audio conversion with bounded FFmpeg execution.

The input is always a server-generated temporary file, never a URL.
FFmpeg / ffprobe must be installed on the host.
"""
import json
import math
import os
import stat
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac"}
OUTPUT_FORMATS = {"mp3": ".mp3", "ogg": ".ogg", "wav": ".wav"}
MAX_DURATION_SECONDS = 600
MAX_AUDIO_OUTPUT_BYTES = 44 * 1024 * 1024
# Bounds are checked from the pinned inode, independent of caller upload checks.
# 50 MiB permits the existing MP4/MOV and verified MP3 result paths.
MAX_PINNED_MEDIA_BYTES = 50 * 1024 * 1024
MAX_CONVERSION_INPUT_BYTES = 20 * 1024 * 1024

# Self-contained audio only: concat, HLS and similar demuxers can dereference
# additional local paths beyond the original user-provided file.
SAFE_AUDIO_DEMUXERS = frozenset({
    "mp3", "wav", "ogg", "flac", "mov,mp4,m4a,3gp,3g2,mj2",
})


@contextmanager
def _pinned_audio_source(source: Path):
    """Keep the *validated inode* open during FFprobe and FFmpeg.

    The backend runs on Linux. /proc/self/fd lets native tools seek within an
    already-validated regular file, even if its original pathname is swapped
    later. No fallback to reopening the untrusted pathname is permitted.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(source, flags)
    except OSError:
        raise ValueError("Не удалось прочитать аудиофайл") from None
    try:
        inode = os.fstat(fd)
        if not stat.S_ISREG(inode.st_mode):
            raise ValueError("Нужен обычный аудиофайл")
        if not 0 < inode.st_size <= MAX_PINNED_MEDIA_BYTES:
            raise ValueError("Медиафайл пустой или превышает 50 МиБ")
        header = os.pread(fd, 16, 0)
        is_wav = header[:4] in (b"RIFF", b"RF64") and header[8:12] == b"WAVE"
        is_mp3 = header.startswith(b"ID3") or (
            len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
        is_ogg = header.startswith(b"OggS")
        is_flac = header.startswith(b"fLaC")
        is_m4a = len(header) >= 8 and header[4:8] == b"ftyp"
        if not (is_wav or is_mp3 or is_ogg or is_flac or is_m4a):
            raise ValueError("Неподдерживаемый аудиоконтейнер")
        if not os.path.isdir("/proc/self/fd"):
            raise ValueError("Защищённая обработка аудио недоступна")
        yield f"/proc/self/fd/{fd}", fd
    except OSError:
        raise ValueError("Не удалось прочитать аудиофайл") from None
    finally:
        os.close(fd)


def _program(name: str) -> str:
    location = shutil.which(name)
    if not location:
        raise ValueError(f"Для конвертации аудио на сервере нужен {name}")
    return location


def _audio_input_options(fd: int) -> tuple[str, ...]:
    """Explicitly disable external MOV/M4A data references for pinned inputs.

    These demuxer flags apply only to ISO BMFF containers. Passing them to
    WAV/MP3/OGG/FLAC causes FFmpeg to reject otherwise valid audio files.
    Inspect the already-open descriptor, never a mutable filename.
    """
    if os.pread(fd, 8, 0)[4:8] == b"ftyp":
        return ("-enable_drefs", "0", "-use_absolute_path", "0")
    return ()


def _probe_pinned_audio(pinned_path: str, fd: int, *, exact: bool) -> dict:
    """Probe an already authenticated, open regular-file descriptor."""
    try:
        result = subprocess.run(
            [
                _program("ffprobe"), "-v", "error",
                "-protocol_whitelist", "file,pipe",
                *_audio_input_options(fd),
                "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
                "-of", "json", pinned_path,
            ],
            capture_output=True, text=True, timeout=12, check=False,
            pass_fds=(fd,),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Не удалось проверить аудио за отведённое время") from None
    if result.returncode != 0:
        raise ValueError("Не удалось прочитать аудиофайл")
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get("format"), dict):
            raise ValueError("Не удалось определить длительность аудио")
        if data["format"].get("format_name") not in SAFE_AUDIO_DEMUXERS:
            raise ValueError("Неподдерживаемый аудиоконтейнер")
        streams = data.get("streams", [])
        if not isinstance(streams, list) or any(
            not isinstance(stream, dict) for stream in streams
        ):
            raise ValueError("Не удалось определить длительность аудио")
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not audio_streams or any(s.get("codec_type") == "video" for s in streams):
            raise ValueError("Нужен аудиофайл без видеодорожки")
        duration = float(data["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_SECONDS:
            raise ValueError("Длительность аудио должна быть не более 10 минут")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and str(error) in (
            "Неподдерживаемый аудиоконтейнер",
            "Нужен аудиофайл без видеодорожки",
            "Длительность аудио должна быть не более 10 минут",
        ):
            raise
        raise ValueError("Не удалось определить длительность аудио") from None
    return {
        "seconds": duration if exact else round(duration, 1),
        "codec": str(audio_streams[0].get("codec_name") or "unknown")[:32],
    }


def probe_audio(source: Path, *, exact: bool = False) -> dict:
    """Probe only the validated inode, not a potentially replaced filename."""
    with _pinned_audio_source(source) as (pinned_path, fd):
        return _probe_pinned_audio(pinned_path, fd, exact=exact)


def convert_audio(source: Path, target: Path, output_format: str) -> dict:
    """Convert safely to a fixed preset, without overwriting a final result.

    Source is owned by the private caller workspace. A unique 0600 staging
    output is created in the same directory as target; only a complete,
    validated result is linked into place. Failures always remove staging.
    """
    fmt = output_format.lower()
    if fmt not in OUTPUT_FORMATS or target.suffix.lower() != OUTPUT_FORMATS[fmt]:
        raise ValueError("Неподдерживаемый формат аудио")
    if target.is_symlink() or target.exists():
        raise ValueError("Файл результата уже существует")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Недопустимый каталог результата")

    presets = {
        "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
        "ogg": ["-c:a", "libopus", "-b:a", "64k", "-ar", "48000"],
        "wav": ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1"],
    }
    expected_codecs = {"mp3": "mp3", "ogg": "opus", "wav": "pcm_s16le"}

    with _pinned_audio_source(source) as (pinned_path, source_fd):
        if os.fstat(source_fd).st_size > MAX_CONVERSION_INPUT_BYTES:
            raise ValueError("Аудиофайл превышает 20 МиБ")
        info = _probe_pinned_audio(pinned_path, source_fd, exact=False)
        temporary_fd, temporary_name = tempfile.mkstemp(
            prefix=".fileshape-audio-convert-",
            suffix=OUTPUT_FORMATS[fmt],
            dir=target.parent,
        )
        os.close(temporary_fd)
        stage = Path(temporary_name)
        try:
            command = [
                _program("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel",
                "error", "-y",
                "-protocol_whitelist", "file,pipe",
                *_audio_input_options(source_fd), "-i", pinned_path,
                "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-map_chapters", "-1",
                "-t", str(MAX_DURATION_SECONDS),
                "-fs", str(MAX_AUDIO_OUTPUT_BYTES),
                *presets[fmt], str(stage),
            ]
            try:
                done = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=65, check=False, pass_fds=(source_fd,),
                )
            except subprocess.TimeoutExpired:
                raise ValueError("Конвертация превысила лимит времени") from None
            if done.returncode != 0 or stage.is_symlink() or not stage.is_file():
                raise ValueError("Не получилось конвертировать аудио в этот формат")
            if not 0 < stage.stat().st_size <= MAX_AUDIO_OUTPUT_BYTES:
                raise ValueError("Результат превысил допустимый размер")
            actual = probe_audio(stage, exact=True)
            if actual["codec"] != expected_codecs[fmt]:
                raise ValueError("Неверный формат результата конвертации")
            if abs(float(actual["seconds"]) - float(info["seconds"])) > 0.5:
                raise ValueError("Не удалось проверить длительность результата")

            stage.chmod(0o600)
            try:
                os.link(stage, target)
            except FileExistsError:
                raise ValueError("Файл результата уже существует") from None
            return info
        finally:
            stage.unlink(missing_ok=True)
