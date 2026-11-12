"""File transformations used by the Telegram handlers.

All source and destination paths must be temporary, server-controlled paths.
"""
from contextlib import ExitStack
from pathlib import Path
import re
import warnings

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

MAX_IMAGE_PIXELS = 35_000_000
MAX_PDF_PAGES = 250
MAX_MERGE_FILES = 5
MAX_SELECTED_PAGES = 150

IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "PDF": ".pdf"}
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _open_image(source: Path) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as original:
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the limit")
            image = ImageOps.exif_transpose(original)
            image.load()
            return image


def convert_image(source: Path, target: Path, fmt: str) -> None:
    fmt = fmt.upper()
    if fmt not in IMAGE_FORMATS:
        raise ValueError("Unsupported image format")
    image = _open_image(source)
    try:
        if fmt in ("JPEG", "PDF"):
            # Transparent pixels turn white, not black.
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                white = Image.new("RGB", rgba.size, "white")
                white.paste(rgba, mask=rgba.getchannel("A"))
                image.close()
                image = white
            else:
                rgb = image.convert("RGB")
                image.close()
                image = rgb
            if fmt == "JPEG":
                image.save(target, format="JPEG", quality=88, optimize=True)
            else:
                image.save(target, format="PDF", resolution=96.0)
        elif fmt == "WEBP":
            image.save(target, format="WEBP", quality=85, method=4)
        else:
            if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                image = image.convert("RGBA")
            image.save(target, format="PNG", optimize=True)
    finally:
        image.close()


def compress_image(source: Path, target: Path) -> None:
    """Save as WebP at quality 72; size reduction is not guaranteed."""
    image = _open_image(source)
    try:
        image.save(target, format="WEBP", quality=72, method=4)
    finally:
        image.close()


def _reader(stream) -> PdfReader:
    reader = PdfReader(stream, strict=False)
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported")
    if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
        raise ValueError("PDF contains too many pages or is empty")
    return reader


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
        with target.open("wb") as output:
            writer.write(output)
        return len(chosen)


def rotate_pdf(source: Path, target: Path, degrees: int = 90) -> int:
    if degrees not in (90, 180, 270):
        raise ValueError("Unsupported rotation")
    with source.open("rb") as stream:
        reader = _reader(stream)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page).rotate(degrees)
        with target.open("wb") as output:
            writer.write(output)
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
        with target.open("wb") as output:
            writer.write(output)
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
        with target.open("wb") as output:
            writer.write(output)
        return len(reader.pages) - len(exclude)
