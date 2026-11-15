"""Plain-text export/import for Word documents (layout is not preserved)."""
from pathlib import Path
import stat
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError
from docx.table import Table
from lxml.etree import XMLSyntaxError

MAX_DOCX_FILES = 300
MAX_DOCX_UNPACKED = 40 * 1024 * 1024
MAX_DOCX_MEMBER = 20 * 1024 * 1024
# Bound the work performed by python-docx when expanding table grid spans.
# Totals are per document, not per table, so many small tables are bounded too.
MAX_DOCX_TABLE_ROWS = 5_000
MAX_DOCX_TABLE_CELLS = 20_000
MAX_DOCX_ROW_CELLS = 64
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 700_000
MAX_TEXT_LINES = 5_000


def validate_docx(source: Path) -> None:
    """Reject oversized or ambiguous Office ZIP packages before XML parsing."""
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = {info.filename for info in entries}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ValueError("Это не документ DOCX")
            if len(entries) > MAX_DOCX_FILES:
                raise ValueError("Слишком сложный документ")
            seen_parts: set[str] = set()
            total = 0
            for info in entries:
                name = info.filename
                part_name = name[:-1] if name.endswith("/") else name
                segments = part_name.split("/")
                if (not part_name or name.startswith("/") or "\\" in name
                        or ":" in name or any(ord(char) < 32 or ord(char) == 127 for char in name)
                        or any(segment in ("", ".", "..") for segment in segments)):
                    raise ValueError("Недопустимый путь элемента DOCX")
                canonical = part_name.casefold()
                if canonical in seen_parts:
                    raise ValueError("Дублирующийся элемент DOCX")
                seen_parts.add(canonical)
                if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise ValueError("Символические ссылки в DOCX запрещены")
                if info.flag_bits & 1:
                    raise ValueError("Зашифрованный DOCX не поддерживается")
                if info.file_size > MAX_DOCX_MEMBER:
                    raise ValueError("Слишком большой элемент документа")
                total += info.file_size
                if total > MAX_DOCX_UNPACKED:
                    raise ValueError("Слишком большой DOCX после распаковки")
                if info.file_size > 128 * 1024 and info.file_size / max(1, info.compress_size) > 250:
                    raise ValueError("Подозрительно сильное сжатие DOCX")
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        raise ValueError("Повреждённый DOCX") from None


def read_docx_text(source: Path) -> tuple[str, dict]:
    validate_docx(source)
    try:
        document = Document(str(source))
    except (XMLSyntaxError, InvalidXmlError, PackageNotFoundError,
            zipfile.BadZipFile, zipfile.LargeZipFile,
            KeyError, ValueError):
        # The archive passed size/path checks but its OOXML is malformed.
        # Do not expose parser output or private input paths to callers.
        raise ValueError("Повреждённый DOCX") from None
    parts = []
    paragraphs = 0
    tables = 0
    length = 0
    total_rows = 0
    total_cells = 0
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            tables += 1
            rows = item.rows
            row_count = len(rows)
            if (row_count > MAX_DOCX_TABLE_ROWS - total_rows
                    or item._column_count > MAX_DOCX_ROW_CELLS):
                raise ValueError("Слишком сложная таблица DOCX")
            total_rows += row_count
            for row in rows:
                # row.cells expands w:gridSpan into repeated cell references.
                # Inspect raw OOXML spans first to avoid a huge tuple allocation.
                grid_cells = 0
                for tc in row._tr.tc_lst:
                    span = tc.grid_span
                    if (span < 1 or span > MAX_DOCX_ROW_CELLS - grid_cells):
                        raise ValueError("Слишком сложная таблица DOCX")
                    grid_cells += span
                if grid_cells > MAX_DOCX_TABLE_CELLS - total_cells:
                    raise ValueError("Слишком сложная таблица DOCX")
                total_cells += grid_cells

                cells = []
                row_chars = 0
                for cell in row.cells:
                    text = cell.text.replace("\n", " ")
                    row_chars += len(text) + (1 if cells else 0)
                    if length + row_chars + 1 > MAX_TEXT_CHARS:
                        raise ValueError("Слишком много текста в документе")
                    cells.append(text)
                parts.append("\t".join(cells))
                length += row_chars + 1
        else:
            paragraphs += 1
            line = item.text
            length += len(line) + 1
            if length > MAX_TEXT_CHARS:
                raise ValueError("Слишком много текста в документе")
            parts.append(line)
    return "\n".join(parts), {"paragraphs": paragraphs, "tables": tables, "characters": length}


def docx_to_txt(source: Path, target: Path) -> dict:
    text, info = read_docx_text(source)
    target.write_text(text, encoding="utf-8")
    return info


def read_plain_text(source: Path) -> str:
    if source.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError("TXT превышает лимит 2 МБ")
    data = source.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Нужен TXT в кодировке UTF-8") from None
    if "\x00" in text:
        raise ValueError("Похоже, это не текстовый файл")
    if len(text) > MAX_TEXT_CHARS or text.count("\n") > MAX_TEXT_LINES:
        raise ValueError("Слишком большой текст для обработки")
    return text


def txt_to_docx(source: Path, target: Path) -> dict:
    text = read_plain_text(source)
    document = Document()
    lines = text.split("\n")
    for line in lines:
        document.add_paragraph(line)
    document.save(str(target))
    return {"lines": len(lines), "characters": len(text)}


def txt_info(source: Path) -> dict:
    text = read_plain_text(source)
    return {"lines": len(text.splitlines()), "characters": len(text)}
