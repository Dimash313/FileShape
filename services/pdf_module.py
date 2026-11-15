"""Typed, in-process PDF domain boundary.

Existing parsing, page limits, and stream cleanup remain in file_tools.
This adapter is deliberately independent of Telegram, FastAPI, storage,
authentication, billing, and request lifecycle management.
"""
from pathlib import Path
from typing import Protocol, runtime_checkable

from services import file_tools


@runtime_checkable
class PdfModulePort(Protocol):
    """Stable PDF operations for any FileShape application ingress."""

    def count_pages(self, source: Path) -> int: ...

    def extract(self, source: Path, target: Path, pages: str) -> int: ...

    def rotate(self, source: Path, target: Path, degrees: int = 90) -> int: ...

    def merge(self, sources: list[Path], target: Path) -> int: ...

    def remove(self, source: Path, target: Path, pages: str) -> int: ...


class ExistingPdfModule:
    """Compatibility adapter around established, bounded PDF functions."""

    def count_pages(self, source: Path) -> int:
        return file_tools.pdf_page_count(source)

    def extract(self, source: Path, target: Path, pages: str) -> int:
        return file_tools.extract_pdf_pages(source, target, pages)

    def rotate(self, source: Path, target: Path, degrees: int = 90) -> int:
        return file_tools.rotate_pdf(source, target, degrees)

    def merge(self, sources: list[Path], target: Path) -> int:
        return file_tools.merge_pdfs(sources, target)

    def remove(self, source: Path, target: Path, pages: str) -> int:
        return file_tools.remove_pdf_pages(source, target, pages)


pdf_module: PdfModulePort = ExistingPdfModule()
