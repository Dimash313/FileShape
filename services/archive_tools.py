"""Bounded ZIP inspection, extraction and archive creation.

Never use ZipFile.extractall() on user archives; user paths are untrusted.
"""
from contextlib import ExitStack, contextmanager
import errno
from pathlib import Path, PurePosixPath
import os
import tempfile
import re
import stat
import time
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


def _inspect_open_zip(archive: zipfile.ZipFile) -> dict:
    """Validate ZIP metadata on the same already-open archive handle."""
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


def inspect_zip(source: Path) -> dict:
    """Validate only a regular, pinned ZIP file; never follow a source link."""
    try:
        with _open_zip_source(source) as (stream, _):
            with zipfile.ZipFile(stream, "r") as archive:
                return _inspect_open_zip(archive)
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        raise ValueError("Повреждённый или неподдерживаемый ZIP") from None

def unpack_zip(source: Path, folder: Path) -> list[tuple[Path, str]]:
    """Stage ZIP extraction and roll back incomplete publication on failure.

    Staged files are hard-linked into place only after every member has
    passed CRC and actual-byte checks. The stage lives on the same filesystem
    as the result, so publishing does not copy up to 50 MiB a second time.
    """
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Каталог распаковки недоступен")

    # Track only files *we* published; never remove pre-existing entries.
    published: list[tuple[Path, int, int]] = []
    try:
        # Pin the approved source and validate on the very same ZIP handle
        # used for reading members. No second pathname open between stages.
        with ExitStack() as reader_stack:
            stream, _ = reader_stack.enter_context(_open_zip_source(source))
            archive = reader_stack.enter_context(zipfile.ZipFile(stream, "r"))
            summary = _inspect_open_zip(archive)
            if not 1 <= summary["files"] <= MAX_EXTRACT_FILES:
                raise ValueError(f"Распаковка доступна для 1–{MAX_EXTRACT_FILES} файлов")
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("Слишком много элементов в ZIP")
            files: list[zipfile.ZipInfo] = []
            declared_total = 0
            for info in members:
                _validate_member(info)
                if not info.is_dir():
                    declared_total += info.file_size
                    if declared_total > MAX_UNCOMPRESSED_TOTAL:
                        raise ValueError("ZIP после распаковки превышает лимит")
                    files.append(info)
            if len(files) != summary["files"] or declared_total != summary["bytes"]:
                raise ValueError("ZIP был изменён во время проверки")

            actual_total = 0
            with tempfile.TemporaryDirectory(
                prefix=".fileshape_extract_", dir=folder,
            ) as staging_name:
                staging = Path(staging_name)
                prepared: list[tuple[Path, Path, str]] = []
                for index, info in enumerate(files, 1):
                    # Keep existing flat, indexed output names and ordering.
                    raw_name = PurePosixPath(info.filename).name
                    clean_name = re.sub(r"[\x00-\x1f\x7f]", "_", raw_name).strip(" .")
                    clean_name = clean_name[:90] or f"file_{index}"
                    safe_name = f"{index:02d}_{clean_name}"
                    staged = staging / safe_name
                    size = 0
                    with archive.open(info, "r") as input_file, staged.open("xb") as output:
                        while True:
                            chunk = input_file.read(64 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            actual_total += len(chunk)
                            if size > MAX_MEMBER_BYTES or actual_total > MAX_UNCOMPRESSED_TOTAL:
                                raise ValueError("Превышен лимит распаковки")
                            output.write(chunk)
                    prepared.append((staged, folder / safe_name, safe_name))

                # A hard link is atomic and fails if dest already exists,
                # including a symlink; unlike os.replace it cannot clobber.
                results = []
                for staged, dest, safe_name in prepared:
                    identity = staged.stat()
                    os.link(staged, dest)
                    published.append((dest, identity.st_dev, identity.st_ino))
                    results.append((dest, safe_name))
                return results
    except BaseException as error:
        # If publication fails halfway through, remove only our own links.
        # In case an external process replaces a path, leave its inode alone.
        for dest, device, inode in reversed(published):
            try:
                current = dest.lstat()
                if (stat.S_ISREG(current.st_mode)
                        and current.st_dev == device and current.st_ino == inode):
                    dest.unlink()
            except OSError:
                # Directory permissions/filesystem errors can prevent cleanup;
                # callers still own their private workspace as a final guard.
                pass
        if isinstance(error, (zipfile.BadZipFile, zipfile.LargeZipFile)):
            raise ValueError("Повреждённый или неподдерживаемый ZIP") from None
        raise


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


@contextmanager
def _open_zip_source(source: Path):
    """Pin a regular source without following a final symlink or blocking FIFO."""
    if source.is_symlink():
        raise ValueError("Файл не найден или недоступен")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENXIO):
            raise ValueError("Файл не найден или недоступен") from None
        raise
    try:
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Файл не найден или недоступен")
        yield stream, info


def _verify_pinned_zip_source(stream, metadata: os.stat_result) -> None:
    """Fail closed if a pinned inode is modified while creating the ZIP.

    An open descriptor pins the original inode despite path replacement.
    Renaming that inode can change ctime without changing its bytes, so
    require unchanged size and mtime, NOT ctime. These checks reject typical
    in-place same-length overwrites but are not a cryptographic snapshot.
    """
    current = os.fstat(stream.fileno())
    if (current.st_dev != metadata.st_dev
            or current.st_ino != metadata.st_ino
            or current.st_size != metadata.st_size
            or current.st_mtime_ns != metadata.st_mtime_ns):
        raise ValueError("Исходный файл изменился во время создания ZIP")


def _write_pinned_zip_members(
    archive: zipfile.ZipFile,
    members: list[tuple],
    stored: set[str],
) -> set[str]:
    """Stream bytes from approved descriptors; never reopen source path.

    Detect changes to the declared length or aggregate limits, including
    growth while writing, and keep the same ZIP name/permissions/timestamps.
    """
    total_written = 0
    high_ratio: set[str] = set()
    for stream, metadata, name in members:
        _verify_pinned_zip_source(stream, metadata)
        stream.seek(0)
        date_time = time.localtime(metadata.st_mtime)[:6]
        if date_time[0] < 1980:
            date_time = (1980, 1, 1, 0, 0, 0)
        entry = zipfile.ZipInfo(name, date_time)
        entry.external_attr = (metadata.st_mode & 0xFFFF) << 16
        entry.create_system = 3 if os.name == "posix" else 0
        entry.file_size = metadata.st_size
        entry.compress_type = (
            zipfile.ZIP_STORED if name in stored else zipfile.ZIP_DEFLATED
        )
        entry._compresslevel = 6
        written = 0
        with archive.open(entry, "w") as dest:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                total_written += len(chunk)
                if (written > metadata.st_size or written > MAX_MEMBER_BYTES
                        or total_written > MAX_UNCOMPRESSED_TOTAL):
                    raise ValueError("Исходный файл изменился во время создания ZIP")
                dest.write(chunk)
        if written != metadata.st_size:
            raise ValueError("Исходный файл изменился во время создания ZIP")
        _verify_pinned_zip_source(stream, metadata)
        if _too_high_compression(archive.getinfo(name)):
            high_ratio.add(name)
    return high_ratio


def make_zip(inputs: list[tuple[Path, str]], target: Path) -> int:
    """Build ZIP from pinned regular input descriptors, with atomic publication.

    Deflate ordinary files. Rebuild extreme-compression members as stored
    data so the unchanged strict ZIP inspector can read our own ZIPs.
    Source paths are opened only once and never followed after approval.
    """
    if not 2 <= len(inputs) <= MAX_BUNDLE_FILES:
        raise ValueError("Выбери от 2 до 5 файлов")

    with ExitStack() as stack:
        used: set[str] = set()
        members: list[tuple] = []
        total_bytes = 0
        for source, suggested_name in inputs:
            stream, metadata = stack.enter_context(_open_zip_source(source))
            if metadata.st_size > MAX_MEMBER_BYTES:
                raise ValueError("Один из файлов слишком большой")
            total_bytes += metadata.st_size
            if total_bytes > MAX_UNCOMPRESSED_TOTAL:
                raise ValueError("ZIP после распаковки превышает лимит")
            members.append((stream, metadata, _archive_name(suggested_name, used)))

        fd, staging_name = tempfile.mkstemp(
            prefix=".fileshape_zip_", suffix=".zip", dir=target.parent,
        )
        os.close(fd)
        staging = Path(staging_name)
        try:
            with zipfile.ZipFile(
                staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as archive:
                store_members = _write_pinned_zip_members(archive, members, set())

            if store_members:
                # Reuse the private staging path; the same approved file
                # descriptors can be rewound, even if their names are swapped.
                with zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                ) as archive:
                    _write_pinned_zip_members(archive, members, store_members)

            # Keep reader compatibility and existing atomic output behavior.
            inspect_zip(staging)
            os.replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)
    return len(inputs)
