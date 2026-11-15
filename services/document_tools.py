"""Plain-text export/import for Word documents (layout is not preserved)."""
from pathlib import Path
from typing import BinaryIO, Callable
import os
import stat
import tempfile
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError
from docx.oxml.ns import qn
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
# python-docx follows w:vMerge continuations recursively through prior rows.
MAX_DOCX_VERTICAL_MERGE_ROWS = 128
# Cumulative across top-level and nested body tables.
MAX_DOCX_TABLES = 200
MAX_DOCX_NESTING_DEPTH = 8
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



def _preflight_docx_tables(document) -> None:
    """Count all body tables, including nested ones, before cell expansion.

    This OOXML-only pass avoids calling python-docx's row.cells on nested
    tables. Accepted files retain the existing plain-text export semantics.
    """
    table_count = 0
    total_rows = 0
    total_cells = 0
    w_tbl = qn("w:tbl")
    w_grid = qn("w:tblGrid")
    w_grid_col = qn("w:gridCol")
    w_tr = qn("w:tr")
    w_tc = qn("w:tc")

    for tbl in document.element.body.iter(w_tbl):
        table_count += 1
        if table_count > MAX_DOCX_TABLES:
            raise ValueError("Слишком много таблиц DOCX")

        depth = 1
        for _ in tbl.iterancestors(w_tbl):
            depth += 1
            if depth > MAX_DOCX_NESTING_DEPTH:
                raise ValueError("Слишком глубокая вложенность таблиц DOCX")

        grid = tbl.find(w_grid)
        if grid is None:
            raise ValueError("Повреждённая таблица DOCX")
        width = 0
        for column in grid:
            if column.tag == w_grid_col:
                width += 1
                if width > MAX_DOCX_ROW_CELLS:
                    raise ValueError("Слишком сложная таблица DOCX")
        if not width:
            raise ValueError("Повреждённая таблица DOCX")

        for row in tbl:
            if row.tag != w_tr:
                continue
            total_rows += 1
            if total_rows > MAX_DOCX_TABLE_ROWS:
                raise ValueError("Слишком сложная таблица DOCX")
            # These numeric attributes are lazily parsed by python-docx.
            # Validate them here so malformed values cannot escape later
            # from row.grid_cols_before or row.cells as raw parser errors.
            try:
                before = row.grid_before
                after = row.grid_after
            except (TypeError, ValueError, OverflowError):
                raise ValueError("Повреждённая таблица DOCX") from None
            if before < 0 or after < 0 or before + after > width:
                raise ValueError("Повреждённая таблица DOCX")
            row_cells = 0
            for tc in row:
                if tc.tag != w_tc:
                    continue
                try:
                    span = tc.grid_span
                    merge = tc.vMerge
                except (TypeError, ValueError, OverflowError):
                    raise ValueError("Повреждённая таблица DOCX") from None
                if merge not in (None, "restart", "continue"):
                    raise ValueError("Повреждённая таблица DOCX")
                if span < 1 or span > MAX_DOCX_ROW_CELLS - row_cells:
                    raise ValueError("Слишком сложная таблица DOCX")
                row_cells += span
                total_cells += span
                if total_cells > MAX_DOCX_TABLE_CELLS:
                    raise ValueError("Слишком сложная таблица DOCX")
            if before + row_cells + after > width:
                raise ValueError("Повреждённая таблица DOCX")


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
    _preflight_docx_tables(document)
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
            # Each grid column remembers (depth, start, end) of its prior
            # cell. Matching the full span prevents ambiguous continuations.
            previous_cells: list[tuple[int, int, int] | None] = [
                None
            ] * item._column_count
            for row in rows:
                # row.cells recursively follows vertical merge continuations.
                # Validate the raw grid before python-docx can recurse/expand.
                grid_cells = 0
                offset = row.grid_cols_before
                current_cells: list[tuple[int, int, int] | None] = [
                    None
                ] * item._column_count
                if offset < 0 or offset > item._column_count:
                    raise ValueError("Повреждённая таблица DOCX")
                for tc in row._tr.tc_lst:
                    span = tc.grid_span
                    if span < 1 or span > MAX_DOCX_ROW_CELLS - grid_cells:
                        raise ValueError("Слишком сложная таблица DOCX")
                    start = offset + grid_cells
                    end = start + span
                    if end > item._column_count:
                        raise ValueError("Повреждённая таблица DOCX")
                    if tc.vMerge == "continue":
                        prior = previous_cells[start]
                        if (prior is None or prior[1:] != (start, end)
                                or any(previous_cells[col] != prior
                                       for col in range(start, end))):
                            raise ValueError("Повреждённая таблица DOCX")
                        depth = prior[0] + 1
                        if depth > MAX_DOCX_VERTICAL_MERGE_ROWS:
                            raise ValueError(
                                "Слишком длинное объединение ячеек DOCX"
                            )
                    else:
                        depth = 1
                    cell = (depth, start, end)
                    for col in range(start, end):
                        current_cells[col] = cell
                    grid_cells += span
                if grid_cells > MAX_DOCX_TABLE_CELLS - total_cells:
                    raise ValueError("Слишком сложная таблица DOCX")
                total_cells += grid_cells
                previous_cells = current_cells

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


def _write_document_atomically(
    target: Path, write_content: Callable[[BinaryIO], None]
) -> None:
    """Publish a complete DOCX or TXT without truncating an old result.

    Callers guarantee the output directory is private and server-controlled.
    """
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            staged = Path(stream.name)
            write_content(stream)
        os.replace(staged, target)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def docx_to_txt(source: Path, target: Path) -> dict:
    text, info = read_docx_text(source)

    def write_text(stream: BinaryIO) -> None:
        stream.write(text.encode("utf-8"))

    _write_document_atomically(target, write_text)
    return info


def read_plain_text(source: Path) -> str:
    # Enforce the byte cap on the actual input, not a pre-read stat result.
    # Files can grow between stat() and read_bytes(); an unbounded read
    # could bypass the byte limit and consume arbitrary memory.
    with source.open("rb") as stream:
        data = stream.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("TXT превышает лимит 2 МБ")
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
    _write_document_atomically(target, document.save)
    return {"lines": len(lines), "characters": len(text)}


def txt_info(source: Path) -> dict:
    text = read_plain_text(source)
    return {"lines": len(text.splitlines()), "characters": len(text)}
