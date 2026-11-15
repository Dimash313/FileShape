"""Safe, bounded, stream-copy editing of tags on user-supplied MP3 files.

The caller owns a private temporary folder and verifies Telegram identity,
file ownership and quota separately. No user-supplied paths or shell commands
are accepted. MP3 with zero/one JPEG/PNG attached artwork is supported.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import unicodedata

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 44 * 1024 * 1024
_FIELDS = ("title", "artist", "album", "date", "genre")


def parse_tag_edits(message: str) -> dict[str, str]:
    """Pipe-separated title/artist/album/year/genre; '-' keep, '~' erase."""
    if not isinstance(message, str) or len(message) > 900:
        raise ValueError("Укажи пять полей через |, максимум 900 символов")
    values = [part.strip() for part in message.split("|")]
    if len(values) != len(_FIELDS):
        raise ValueError("Нужно пять полей: название | исполнитель | альбом | год | жанр")
    changes = {}
    for name, value in zip(_FIELDS, values):
        if value == "-":
            continue
        if value == "~":
            changes[name] = ""
            continue
        if not value or len(value) > 120 or len(value.encode("utf-8", errors="replace")) > 480:
            raise ValueError("Каждое поле должно содержать от 1 до 120 символов")
        if any(unicodedata.category(ch).startswith("C") for ch in value):
            raise ValueError("Недопустимые управляющие символы в тегах")
        if name == "date" and not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("Год должен содержать четыре цифры")
        changes[name] = value
    if not changes:
        raise ValueError("Нет изменений. Укажи значение или ~ для очистки тега")
    return changes


def _tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise ValueError(f"Для редактирования MP3 требуется {name}")
    return value


def _check_path(path: Path, *, source: bool) -> Path:
    if not isinstance(path, Path) or path.suffix.lower() != ".mp3":
        raise ValueError("Поддерживаются только MP3-файлы")
    if path.is_symlink():
        raise ValueError("Символические ссылки запрещены")
    if source:
        try:
            info = path.stat()
        except OSError:
            raise ValueError("Исходный файл недоступен") from None
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SOURCE_BYTES:
            raise ValueError("Размер MP3 должен быть от 1 байта до 20 МБ")
        with path.open("rb") as stream:
            head = stream.read(4)
        if not (head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 255 and head[1] & 224 == 224)):
            raise ValueError("Содержимое не соответствует MP3")
    elif path.exists() or not path.parent.is_dir():
        raise ValueError("Путь результата уже занят или недоступен")
    return path


def _inspect(source: Path) -> dict:
    try:
        completed = subprocess.run(
            [_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
             "-show_entries", "stream=index,codec_name,codec_type:stream_disposition=attached_pic:format=format_name,duration:format_tags=title,artist,album,date,genre",
             "-of", "json", str(source)],
            capture_output=True, timeout=12, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Истекло время проверки MP3") from None
    if completed.returncode != 0 or len(completed.stdout) > 32_768:
        raise ValueError("Не удалось прочитать метаданные MP3")
    try:
        obj = json.loads(completed.stdout)
        if "mp3" not in obj["format"]["format_name"].split(","):
            raise ValueError("Файл не является MP3")
        from services.audio_tools import MAX_DURATION_SECONDS
        length = float(obj["format"]["duration"])
        if not 0 < length <= MAX_DURATION_SECONDS:
            raise ValueError("Длительность записи должна быть не более 10 минут")
        streams = obj["streams"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        cover = [s for s in streams if s.get("codec_type") == "video"]
        if len(audio) != 1 or audio[0].get("codec_name") != "mp3":
            raise ValueError("Нужна одна MP3-аудиодорожка")
        if len(cover) > 1 or any(
            s.get("codec_name") not in {"mjpeg", "png"}
            or s.get("disposition", {}).get("attached_pic") != 1
            for s in cover
        ) or len(audio) + len(cover) != len(streams):
            raise ValueError("Обнаружены неподдерживаемые дорожки или обложка")
        tags = obj.get("format", {}).get("tags", {})
        return {"audio_codec": "mp3", "cover_index": cover[0]["index"] if cover else None,
                "tags": {k: str(tags[k]) for k in _FIELDS if k in tags}}
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        if isinstance(error, ValueError) and str(error) in {
            "Файл не является MP3", "Длительность записи должна быть не более 10 минут",
            "Нужна одна MP3-аудиодорожка", "Обнаружены неподдерживаемые дорожки или обложка",
        }:
            raise
        raise ValueError("Некорректная структура MP3") from None


def edit_mp3_tags(source: Path, target: Path, edits: dict[str, str]) -> dict:
    """Copy MP3 audio and optional attached cover; edit five bounded ID3 tags."""
    _check_path(source, source=True)
    _check_path(target, source=False)
    if source.resolve() == target.resolve():
        raise ValueError("Входной и выходной файлы должны различаться")
    if not isinstance(edits, dict) or not edits or set(edits) - set(_FIELDS):
        raise ValueError("Недопустимые поля метаданных")
    for key, value in edits.items():
        if not isinstance(value, str) or len(value) > 120:
            raise ValueError("Недопустимое значение тега")
        if value and (any(unicodedata.category(ch).startswith("C") for ch in value)
                      or (key == "date" and re.fullmatch(r"[0-9]{4}", value) is None)):
            raise ValueError("Недопустимое значение тега")
    input_info = _inspect(source)
    cmd = [
        _tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-n", "-protocol_whitelist", "file,pipe", "-i", str(source),
        "-map", "0:a:0",
    ]
    if input_info["cover_index"] is not None:
        cmd.extend(["-map", f"0:{input_info['cover_index']}"])
    cmd.extend(["-c", "copy", "-map_metadata", "0", "-map_chapters", "-1"])
    if input_info["cover_index"] is not None:
        cmd.extend(["-disposition:v:0", "attached_pic"])
    for key, value in edits.items():
        cmd.extend(["-metadata", f"{key}={value}"])
    cmd.extend(["-id3v2_version", "3", "-write_id3v1", "0",
                "-fs", str(MAX_OUTPUT_BYTES), str(target)])
    succeeded = False
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=65, check=False)
        if result.returncode != 0 or not target.is_file():
            raise ValueError("Не удалось сохранить теги MP3")
        if not 0 < target.stat().st_size <= MAX_OUTPUT_BYTES:
            raise ValueError("Результат превышает лимит 44 МБ")
        output_info = _inspect(target)
        if (output_info["audio_codec"] != input_info["audio_codec"]
                or (output_info["cover_index"] is None) != (input_info["cover_index"] is None)):
            raise ValueError("Не удалось сохранить дорожку или обложку")
        for key, value in edits.items():
            if output_info["tags"].get(key, "") != value:
                raise ValueError("Изменённые теги не сохранились")
        succeeded = True
        return output_info["tags"]
    except subprocess.TimeoutExpired:
        raise ValueError("Истекло время сохранения тегов") from None
    finally:
        if not succeeded:
            target.unlink(missing_ok=True)
