"""Plain-text export/import for Word documents (layout is not preserved)."""
from pathlib import Path
import zipfile

from docx import Document
from docx.table import Table

MAX_DOCX_FILES = 300
MAX_DOCX_UNPACKED = 40 * 1024 * 1024
MAX_DOCX_MEMBER = 20 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 700_000
MAX_TEXT_LINES = 5_000


def validate_docx(source: Path) -> None:
    """Reject oversized Office packages before python-docx parses their XML."""
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = {info.filename for info in entries}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ValueError("Это не документ DOCX")
            if len(entries) > MAX_DOCX_FILES:
                raise ValueError("Слишком сложный документ")
            total = 0
            for info in entries:
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
    document = Document(str(source))
    parts = []
    paragraphs = 0
    tables = 0
    length = 0
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            tables += 1
            for row in item.rows:
                line = "\t".join(cell.text.replace("\n", " ") for cell in row.cells)
                parts.append(line)
                length += len(line) + 1
        else:
            paragraphs += 1
            line = item.text
            parts.append(line)
            length += len(line) + 1
        if length > MAX_TEXT_CHARS:
            raise ValueError("Слишком много текста в документе")
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
