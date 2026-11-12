"""DOCX and TXT conversion tests (plain text, not layout reproduction)."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from docx import Document

from services.document_tools import (
    docx_to_txt,
    read_docx_text,
    txt_info,
    txt_to_docx,
    validate_docx,
)


class DocumentToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_txt_to_docx_to_txt(self):
        source = self.folder / "hello.txt"
        docx = self.folder / "hello.docx"
        output = self.folder / "back.txt"
        source.write_text("Привет\nWorld", encoding="utf-8")
        self.assertEqual(txt_to_docx(source, docx)["lines"], 2)
        info = docx_to_txt(docx, output)
        self.assertEqual(info["paragraphs"], 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "Привет\nWorld")
        self.assertEqual(txt_info(source)["lines"], 2)

    def test_extract_table_text(self):
        docx = self.folder / "table.docx"
        document = Document()
        document.add_paragraph("Intro")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "A"
        table.cell(0, 1).text = "B"
        document.save(docx)
        text, info = read_docx_text(docx)
        self.assertIn("A\tB", text)
        self.assertEqual(info["tables"], 1)

    def test_reject_binary_txt(self):
        source = self.folder / "bad.txt"
        source.write_bytes(b"abc\x00def")
        with self.assertRaises(ValueError):
            txt_to_docx(source, self.folder / "bad.docx")

    def test_reject_fake_docx(self):
        source = self.folder / "fake.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("not-document.txt", "hello")
        with self.assertRaises(ValueError):
            validate_docx(source)


if __name__ == "__main__":
    unittest.main()
