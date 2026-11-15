"""Bounded PDF operations on private, server-controlled temporary paths.

This format-specific module owns PDF limits, page selection and parsing.
Callers must still enforce authorization, upload limits and artifact cleanup.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import re
import tempfile

from pypdf import PdfReader, PdfWriter

MAX_PDF_PAGES = 250
MAX_MERGE_FILES = 5
MAX_SELECTED_PAGES = 150

def _reader(stream) -> PdfReader:
    reader = PdfReader(stream, strict=False)
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported")
    if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
        raise ValueError("PDF contains too many pages or is empty")
    return reader


def _write_pdf_atomically(writer: PdfWriter, target: Path) -> None:
    """Publish only a complete PDF; preserve the previous output on errors.

    The temporary file lives in the target directory to keep os.replace
    atomic and has restrictive permissions from NamedTemporaryFile.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            writer.write(output)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def pdf_page_count(source: Path) -> int:
    with source.open("rb") as stream:
        return len(_reader(stream).pages)


def parse_page_selection(value: str, total_pages: int) -> list[int]:
    """Parse '1,3-5' into zero-based page indexes in the requested order."""
    if not 1 <= total_pages <= MAX_PDF_PAGES:
        raise ValueError("Unsupported page count")
    if not re.fullmatch(r"[0-9,\s-]{1,90}", value):
        raise ValueError("Use page numbers, e.g. 1,3-5")
    selection: list[int] = []
    seen: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Empty page number")
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2 or not all(p.strip().isdigit() for p in bounds):
                raise ValueError("Invalid page range")
            start, end = (int(p) for p in bounds)
            if start > end:
                raise ValueError("A range must be ascending")
        elif part.isdigit():
            start = end = int(part)
        else:
            raise ValueError("Invalid page number")
        if start < 1 or end > total_pages:
            raise ValueError(f"Page must be between 1 and {total_pages}")
        if end - start + 1 > MAX_SELECTED_PAGES:
            raise ValueError("Too many pages selected")
        for page in range(start, end + 1):
            if page not in seen:
                selection.append(page - 1)
                seen.add(page)
            if len(selection) > MAX_SELECTED_PAGES:
                raise ValueError("Too many pages selected")
    if not selection:
        raise ValueError("No pages selected")
    return selection


def extract_pdf_pages(source: Path, target: Path, pages: str) -> int:
    with source.open("rb") as stream:
        reader = _reader(stream)
        chosen = parse_page_selection(pages, len(reader.pages))
        writer = PdfWriter()
        for index in chosen:
            writer.add_page(reader.pages[index])
        _write_pdf_atomically(writer, target)
        return len(chosen)


def rotate_pdf(source: Path, target: Path, degrees: int = 90) -> int:
    if degrees not in (90, 180, 270):
        raise ValueError("Unsupported rotation")
    with source.open("rb") as stream:
        reader = _reader(stream)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page).rotate(degrees)
        _write_pdf_atomically(writer, target)
        return len(reader.pages)


def merge_pdfs(sources: list[Path], target: Path) -> int:
    if not 2 <= len(sources) <= MAX_MERGE_FILES:
        raise ValueError("Select 2 to 5 PDF files")
    with ExitStack() as stack:
        writer = PdfWriter()
        total = 0
        for source in sources:
            stream = stack.enter_context(source.open("rb"))
            reader = _reader(stream)
            total += len(reader.pages)
            if total > MAX_PDF_PAGES:
                raise ValueError("Combined PDF exceeds page limit")
            for page in reader.pages:
                writer.add_page(page)
        _write_pdf_atomically(writer, target)
        return total


def remove_pdf_pages(source: Path, target: Path, pages: str) -> int:
    """Create a copy of PDF excluding specified 1-based page numbers."""
    with source.open("rb") as stream:
        reader = _reader(stream)
        exclude = set(parse_page_selection(pages, len(reader.pages)))
        if len(exclude) == len(reader.pages):
            raise ValueError("Нельзя удалить все страницы PDF")
        writer = PdfWriter()
        for index, page in enumerate(reader.pages):
            if index not in exclude:
                writer.add_page(page)
        _write_pdf_atomically(writer, target)
        return len(reader.pages) - len(exclude)
