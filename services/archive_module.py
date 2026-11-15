"""Typed in-process ZIP archive domain boundary.

The adapter preserves existing validated ZIP inspection, bounded extraction
and archive creation. It does not authorize users, select arbitrary paths,
reserve quotas, or own temporary workspace cleanup.
"""
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from services import archive_tools


class ArchiveInfo(TypedDict):
    files: int
    bytes: int
    names: list[str]


@runtime_checkable
class ArchiveModulePort(Protocol):
    """ZIP operations for bot/API callers without transport dependencies."""

    def inspect(self, source: Path) -> ArchiveInfo: ...

    def extract(self, source: Path, folder: Path) -> list[tuple[Path, str]]: ...

    def create(self, inputs: list[tuple[Path, str]], target: Path) -> int: ...


class ExistingArchiveModule:
    """Delegate unchanged to the original bounded ZIP implementation."""

    def inspect(self, source: Path) -> ArchiveInfo:
        return archive_tools.inspect_zip(source)

    def extract(self, source: Path, folder: Path) -> list[tuple[Path, str]]:
        return archive_tools.unpack_zip(source, folder)

    def create(self, inputs: list[tuple[Path, str]], target: Path) -> int:
        return archive_tools.make_zip(inputs, target)


archive_module: ArchiveModulePort = ExistingArchiveModule()
