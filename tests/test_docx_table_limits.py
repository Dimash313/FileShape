"""Bounded DOCX table expansion and text extraction regression tests."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document

from services import document_tools
from services.document_module import document_module


class DocxTableLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "input.docx"
        self.target = self.root / "result.txt"

    def make_tables(self, *, count=1, rows=1, cols=2):
        doc = Document()
        for _ in range(count):
            table = doc.add_table(rows=rows, cols=cols)
            for row in table.rows:
                for cell in row.cells:
                    cell.text = "X"
        doc.save(self.source)

    def assert_rejected_without_output(self, message):
        with self.assertRaisesRegex(ValueError, message):
            document_module.to_text(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_valid_table_order_and_text_budget_boundary(self):
        doc = Document()
        doc.add_paragraph("Intro")
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "A\nB"
        table.cell(0, 1).text = "C"
        doc.add_paragraph("End")
        doc.save(self.source)
        info = document_module.to_text(self.source, self.target)
        expected = "Intro\nA B\tC\nEnd"
        self.assertEqual(self.target.read_text(encoding="utf-8"), expected)
        self.assertEqual(info["tables"], 1)
        self.assertEqual(info["paragraphs"], 2)
        self.assertEqual(info["characters"], len(expected) + 1)

    def test_total_row_budget_shared_across_tables(self):
        self.make_tables(count=2, rows=1, cols=1)
        with patch.object(document_tools, "MAX_DOCX_TABLE_ROWS", 1):
            self.assert_rejected_without_output("Слишком сложная таблица")

    def test_total_expanded_cell_budget_shared_across_tables(self):
        self.make_tables(count=2, rows=1, cols=2)
        with patch.object(document_tools, "MAX_DOCX_TABLE_CELLS", 3):
            self.assert_rejected_without_output("Слишком сложная таблица")

    def test_row_grid_width_budget(self):
        self.make_tables(rows=1, cols=2)
        with patch.object(document_tools, "MAX_DOCX_ROW_CELLS", 1):
            self.assert_rejected_without_output("Слишком сложная таблица")

    def test_malicious_huge_grid_span_rejected_before_expansion(self):
        doc = Document()
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).merge(table.cell(0, 1)).text = "Safe"
        doc.save(self.source)
        malicious = self.root / "huge-span.docx"
        with zipfile.ZipFile(self.source) as source:
            with zipfile.ZipFile(malicious, "w") as target:
                changed = False
                for entry in source.infolist():
                    data = source.read(entry.filename)
                    if entry.filename == "word/document.xml":
                        self.assertIn(b'<w:gridSpan w:val="2"/>', data)
                        data = data.replace(
                            b'<w:gridSpan w:val="2"/>',
                            b'<w:gridSpan w:val="1000000"/>',
                            1,
                        )
                        changed = True
                    target.writestr(entry, data)
                self.assertTrue(changed)
        self.source = malicious
        document_tools.validate_docx(self.source)
        self.assert_rejected_without_output("Слишком сложная таблица")

    def test_cell_text_budget_stops_oversize_export(self):
        doc = Document()
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "1234"
        table.cell(0, 1).text = "5678"
        doc.save(self.source)
        with patch.object(document_tools, "MAX_TEXT_CHARS", 9):
            self.assert_rejected_without_output("Слишком много текста")
        # Exactly ten accounted characters: 4 + tab + 4 + newline.
        with patch.object(document_tools, "MAX_TEXT_CHARS", 10):
            info = document_module.to_text(self.source, self.target)
        self.assertEqual(info["characters"], 10)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "1234\t5678")


if __name__ == "__main__":
    unittest.main()
