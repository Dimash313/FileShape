"""Bounded ZIP inspection, extraction and archive creation.

Never use ZipFile.extractall() on user archives; user paths are untrusted.
"""
from pathlib import Path, PurePosixPath
import os
import tempfile
import re
import stat
import zipfile

MAX_ARCHIVE_ENTRIES = 100
MAX_EXTRACT_FILES = 10
MAX_BUNDLE_FILES = 5
MAX_UNCOMPRESSED_TOTAL = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def _too_high_compression(info: zipfile.ZipInfo) -> bool:
    """The same safety threshold for external ZIPs and our own output."""
    return (
        info.file_size > 128 * 1024
        and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO
    )


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ValueError("В архиве есть небезопасное имя файла")
    parts = PurePosixPath(name).parts
    if ".." in parts or not parts:
        raise ValueError("В архиве есть небезопасный путь")
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or stat.S_ISLNK(mode):
        raise ValueError("Символические ссылки и специальные файлы не поддерживаются")
    if info.flag_bits & 1:
        raise ValueError("Зашифрованные ZIP не поддерживаются")
    if not info.is_dir():
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("Один из файлов слишком большой")
        if _too_high_compression(info):
            raise ValueError("Подозрительно сильное сжатие в ZIP")


def inspect_zip(source: Path) -> dict:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("Слишком много элементов в ZIP")
            total = 0
            filenames = []
            for info in members:
                _validate_member(info)
                if not info.is_dir():
                    total += info.file_size
                    if total > MAX_UNCOMPRESSED_TOTAL:
                        raise ValueError("ZIP после распаковки превышает лимит")
                    filenames.append(info.filename)
            return {"files": len(filenames), "bytes": total, "names": filenames[:15]}
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        raise ValueError("Повреждённый или неподдерживаемый ZIP") from None


def unpack_zip(source: Path, folder: Path) -> list[tuple[Path, str]]:
    summary = inspect_zip(source)
    if not 1 <= summary["files"] <= MAX_EXTRACT_FILES:
        raise ValueError(f"Распаковка доступна для 1–{MAX_EXTRACT_FILES} файлов")
    result = []
    actual_total = 0
    with zipfile.ZipFile(source, "r") as archive:
        for index, info in enumerate((info for info in archive.infolist() if not info.is_dir()), 1):
            # Basename only: prevent Zip Slip, even when folders are nested.
            raw_name = PurePosixPath(info.filename).name
            clean_name = re.sub(r"[\x00-\x1f\x7f]", "_", raw_name).strip(" .")
            clean_name = clean_name[:90] or f"file_{index}"
            safe_name = f"{index:02d}_{clean_name}"
            dest = folder / safe_name
            size = 0
            with archive.open(info, "r") as input_file, dest.open("wb") as output:
                while True:
                    chunk = input_file.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    actual_total += len(chunk)
                    if size > MAX_MEMBER_BYTES or actual_total > MAX_UNCOMPRESSED_TOTAL:
                        raise ValueError("Превышен лимит распаковки")
                    output.write(chunk)
            result.append((dest, safe_name))
    return result


def _archive_name(name: str, used: set[str]) -> str:
    candidate = name.replace("\\", "/").split("/")[-1]
    candidate = re.sub(r"[\x00-\x1f\x7f]", "_", candidate).strip(" .")
    candidate = candidate[:90] or "file"
    stem, dot, extension = candidate.rpartition(".")
    if not stem:
        stem, extension, dot = candidate, "", ""
    result = candidate
    index = 2
    while result.casefold() in used:
        result = f"{stem}_{index}{dot}{extension}"
        index += 1
    used.add(result.casefold())
    return result


def make_zip(inputs: list[tuple[Path, str]], target: Path) -> int:
    """Create a ZIP that our strict reader can inspect and extract.

    Deflate normally. Only if one or more members exceed the reader's
    compression-ratio threshold, rebuild those members as ZIP_STORED.
    This preserves compression for normal files and does NOT relax the
    ZIP-bomb policy for untrusted external archives.

    Staging in the output directory avoids publishing an invalid or
    partially-written archive and preserves an existing target on errors.
    """
    if not 2 <= len(inputs) <= MAX_BUNDLE_FILES:
        raise ValueError("Выбери от 2 до 5 файлов")
    used: set[str] = set()
    members: list[tuple[Path, str]] = []
    total_bytes = 0
    for source, suggested_name in inputs:
        if source.is_symlink() or not source.is_file():
            raise ValueError("Файл не найден или недоступен")
        size = source.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise ValueError("Один из файлов слишком большой")
        total_bytes += size
        if total_bytes > MAX_UNCOMPRESSED_TOTAL:
            raise ValueError("ZIP после распаковки превышает лимит")
        members.append((source, _archive_name(suggested_name, used)))

    fd, staging_name = tempfile.mkstemp(
        prefix=".fileshape_zip_", suffix=".zip", dir=target.parent,
    )
    os.close(fd)
    staging = Path(staging_name)
    try:
        store_members: set[str] = set()
        with zipfile.ZipFile(
            staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
        ) as archive:
            for source, name in members:
                archive.write(source, arcname=name)
                if _too_high_compression(archive.getinfo(name)):
                    store_members.add(name)

        if store_members:
            # Reuse the same private temporary path: no second on-disk
            # archive or duplicate data storage is needed.
            with zipfile.ZipFile(
                staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as archive:
                for source, name in members:
                    compression = (
                        zipfile.ZIP_STORED if name in store_members
                        else zipfile.ZIP_DEFLATED
                    )
                    archive.write(source, arcname=name, compress_type=compression)

        # Fail closed if source bytes changed during the optional rebuild,
        # or if future reader rules become stricter.
        inspect_zip(staging)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)
    return len(inputs)
