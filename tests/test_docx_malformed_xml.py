"""Regression tests for corrupted DOCX XML and package parser failures.

Fixtures use temporary locally generated DOCX files; no network or binary
samples are committed. Test only the DOCX domain port, not HTTP or Telegram.
"""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError

from services import document_tools
from services.document_module import document_module


BROKEN_PARTS = (
    "word/document.xml",
    "[Content_Types].xml",
    "_rels/.rels",
    "word/_rels/document.xml.rels",
)


class MalformedDocxXmlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original.docx"
        word = Document()
        word.add_paragraph("Safe sample")
        word.save(self.source)

    def _corrupt_xml(self, part: str) -> Path:
        target = self.root / "corrupt.docx"
        with zipfile.ZipFile(self.source, "r") as original:
            with zipfile.ZipFile(target, "w") as corrupted:
                found = False
                for entry in original.infolist():
                    payload = original.read(entry.filename)
                    if entry.filename == part:
                        payload = b"<broken-xml"
                        found = True
                    corrupted.writestr(entry, payload)
        self.assertTrue(found, f"Fixture missing {part}")
        return target

    def test_corrupt_core_and_relationship_xml_is_stably_rejected(self):
        for part in BROKEN_PARTS:
            with self.subTest(part=part):
                source = self._corrupt_xml(part)
                # ZIP limits and required filenames alone must not mask this.
                document_tools.validate_docx(source)
                with self.assertRaises(ValueError) as caught:
                    document_module.inspect_docx(source)
                self.assertEqual(str(caught.exception), "Повреждённый DOCX")

                output = self.root / "result.txt"
                with self.assertRaises(ValueError) as caught:
                    document_module.to_text(source, output)
                self.assertEqual(str(caught.exception), "Повреждённый DOCX")
                self.assertFalse(output.exists())

    def test_package_parser_failures_are_normalized_but_os_errors_propagate(self):
        for problem in (
            InvalidXmlError("internal XML issue"),
            PackageNotFoundError("private source name"),
            zipfile.BadZipFile("bad crc"),
            KeyError("private/word/document.xml"),
            ValueError("file /private/source.docx is not a Word file"),
        ):
            with self.subTest(problem=type(problem).__name__):
                with patch.object(document_tools, "Document", side_effect=problem):
                    with self.assertRaises(ValueError) as caught:
                        document_module.inspect_docx(self.source)
                self.assertEqual(str(caught.exception), "Повреждённый DOCX")

        with patch.object(document_tools, "Document", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                document_module.inspect_docx(self.source)

    def test_valid_document_preserves_text_export(self):
        output = self.root / "result.txt"
        info = document_module.inspect_docx(self.source)
        self.assertEqual(info["paragraphs"], 1)
        document_module.to_text(self.source, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "Safe sample")


if __name__ == "__main__":
    unittest.main()
