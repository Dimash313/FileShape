"""Strict, low-cost content checks before passing uploads to parsers.

Extensions select supported operations; signatures reject mislabeled payloads.
These checks are not a replacement for process isolation and resource limits.
"""
from pathlib import Path
import zipfile

from PIL import Image, UnidentifiedImageError

from services.audio_tools import AUDIO_EXTENSIONS

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_SIGNATURES = {
    ".mp3": lambda head: head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xff and (head[1] & 0xe0) == 0xe0
    ),
    ".wav": lambda head: head.startswith(b"RIFF") and head[8:12] == b"WAVE",
    ".ogg": lambda head: head.startswith(b"OggS"),
    ".oga": lambda head: head.startswith(b"OggS"),
    ".flac": lambda head: head.startswith(b"fLaC"),
    ".m4a": lambda head: len(head) >= 12 and head[4:8] == b"ftyp",
}


def validate_upload(source: Path, suffix: str) -> None:
    """Reject obviously invalid content; never use untrusted names as paths."""
    suffix = suffix.lower()
    with source.open("rb") as stream:
        head = stream.read(32)

    if suffix in IMAGE_EXTENSIONS:
        try:
            with Image.open(source) as image:
                actual = image.format
        except (OSError, ValueError, UnidentifiedImageError):
            raise ValueError("Файл не является поддерживаемым изображением") from None
        allowed = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
        if actual != allowed[suffix]:
            raise ValueError("Формат изображения не совпадает с расширением")
    elif suffix == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise ValueError("Файл не является PDF")
    elif suffix in {".docx", ".zip"}:
        if not zipfile.is_zipfile(source):
            raise ValueError("Файл не является корректным ZIP/DOCX")
    elif suffix in AUDIO_EXTENSIONS:
        check = AUDIO_SIGNATURES.get(suffix)
        if check is None or not check(head):
            raise ValueError("Формат аудиофайла не совпадает с расширением")
    elif suffix == ".txt":
        if b"\x00" in head:
            raise ValueError("TXT содержит недопустимые двоичные данные")
    else:
        raise ValueError("Неподдерживаемый формат файла")
