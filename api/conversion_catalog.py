"""Single source of truth for supported API file operations.

The catalog intentionally preserves the existing public action strings and
suffix classification. It is not a plugin loader, authorization layer, or
permission to dynamically execute user-supplied actions.
"""
from pathlib import Path

from services.audio_tools import AUDIO_EXTENSIONS

SUPPORTED: dict[str, set[str]] = {
    "image": {"img:JPEG", "img:PNG", "img:WEBP", "img:PDF", "img:compress"},
    "pdf": {"pdf:rotate", "pdf:first", "pdf:extract", "pdf:remove", "pdf:info"},
    "audio": {"audio:mp3", "audio:ogg", "audio:wav", "audio:info"},
    "docx": {"docx:txt", "docx:info"},
    "txt": {"txt:docx", "txt:info"},
    "archive": {"zip:list"},
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def file_kind(filename: str) -> tuple[str, str]:
    """Classify a client filename without opening or trusting its contents.

    Upload validation and content parsing happen separately in the sandboxed
    worker. Normalizing backslashes preserves existing Windows-path behavior.
    """
    suffix = Path(filename.replace("\\", "/")).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image", suffix
    if suffix == ".pdf":
        return "pdf", suffix
    if suffix in AUDIO_EXTENSIONS:
        return "audio", suffix
    if suffix in {".docx", ".txt"}:
        return suffix[1:], suffix
    if suffix == ".zip":
        return "archive", suffix
    return "other", suffix
