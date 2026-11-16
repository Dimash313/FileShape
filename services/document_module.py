"""Typed in-process DOCX/TXT domain boundary.

This is a compatibility adapter over the current bounded document
functions. Documents are intentionally treated as text import/export;
the original DOCX page layout is not preserved. The application edge
still owns authorization, quota, upload validation and temporary files.
"""
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from services import document_tools


class DocxInfo(TypedDict):
    paragraphs: int
    tables: int
    characters: int


class TextInfo(TypedDict):
    lines: int
    characters: int


@runtime_checkable
class DocumentModulePort(Protocol):
    """Document operations independent of API and Telegram transport."""

    def inspect_docx(self, source: Path) -> DocxInfo: ...

    def inspect_text(self, source: Path) -> TextInfo: ...

    def to_text(self, source: Path, target: Path) -> DocxInfo: ...

    def to_docx(self, source: Path, target: Path) -> TextInfo: ...


class ExistingDocumentModule:
    """Delegate to the same validated DOCX and UTF-8 text functions."""

    def inspect_docx(self, source: Path) -> DocxInfo:
        _text, info = document_tools.read_docx_text(source)
        return info

    def inspect_text(self, source: Path) -> TextInfo:
        return document_tools.txt_info(source)

    def to_text(self, source: Path, target: Path) -> DocxInfo:
        return document_tools.docx_to_txt(source, target)

    def to_docx(self, source: Path, target: Path) -> TextInfo:
        return document_tools.txt_to_docx(source, target)


document_module: DocumentModulePort = ExistingDocumentModule()
