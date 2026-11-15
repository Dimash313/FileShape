"""DOCX nested table resource limits must include all descendant w:tbl nodes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document

from services import document_tools
from services.document_module import document_module


class NestedTableBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "nested.docx"
        self.target = self.root / "export.txt"

    def make_nested(self, *, rows=3, cols=2, nested_count=1):
        doc = Document()
        outer = doc.add_table(rows=1, cols=nested_count)
        for cell in outer.rows[0].cells:
            cell.text = "Outer"
            nested = cell.add_table(rows=rows, cols=cols)
            nested.cell(0, 0).text = "Hidden inner text"
        doc.save(self.source)
        return doc

    def assert_rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            document_module.to_text(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_normal_nested_tables_keep_existing_plaintext_export(self):
        doc = Document()
        doc.add_paragraph("Before")
        outer = doc.add_table(rows=1, cols=1)
        outer.cell(0, 0).text = "Outer"
        outer.cell(0, 0).add_table(rows=2, cols=2).cell(0, 0).text = "Hidden"
        doc.add_paragraph("After")
        doc.save(self.source)
        info = document_module.to_text(self.source, self.target)
        output = self.target.read_text(encoding="utf-8")
        self.assertEqual(output, "Before\nOuter \nAfter")
        self.assertNotIn("Hidden", output)
        self.assertEqual(info["tables"], 1)
        self.assertEqual(info["paragraphs"], 2)

    def test_nested_rows_share_document_budget(self):
        self.make_nested(rows=4, cols=1)
        self.assertEqual(len(Document(self.source).tables[0].rows), 1)
        with patch.object(document_tools, "MAX_DOCX_TABLE_ROWS", 4):
            self.assert_rejected("Слишком сложная таблица")

    def test_nested_cells_share_document_budget(self):
        self.make_nested(rows=2, cols=2)
        # Outer one cell + inner four cells = five cells.
        with patch.object(document_tools, "MAX_DOCX_TABLE_CELLS", 4):
            self.assert_rejected("Слишком сложная таблица")

    def test_total_count_includes_nested_tables(self):
        self.make_nested(rows=1, cols=1, nested_count=2)
        with patch.object(document_tools, "MAX_DOCX_TABLES", 2):
            self.assert_rejected("Слишком много таблиц")

    def test_nesting_depth_limit(self):
        doc = Document()
        outer = doc.add_table(rows=1, cols=1)
        inner = outer.cell(0, 0).add_table(rows=1, cols=1)
        inner.cell(0, 0).add_table(rows=1, cols=1)
        doc.save(self.source)
        with patch.object(document_tools, "MAX_DOCX_NESTING_DEPTH", 2):
            self.assert_rejected("Слишком глубокая вложенность")

    def test_nested_grid_width_cannot_bypass_row_width_limit(self):
        self.make_nested(rows=1, cols=3)
        with patch.object(document_tools, "MAX_DOCX_ROW_CELLS", 2):
            self.assert_rejected("Слишком сложная таблица")

    def test_nested_oversized_grid_span_is_checked_before_row_cells(self):
        doc = self.make_nested(rows=1, cols=2)
        tc = doc.tables[0].cell(0, 0).tables[0].rows[0]._tr.tc_lst[0]
        tc.get_or_add_tcPr().get_or_add_gridSpan().val = 1_000_000
        doc.save(self.source)
        self.assert_rejected("Слишком сложная таблица")

    def test_valid_nested_horizontal_merge(self):
        doc = self.make_nested(rows=1, cols=2)
        inner = doc.tables[0].cell(0, 0).tables[0]
        inner.cell(0, 0).merge(inner.cell(0, 1)).text = "Merged"
        doc.save(self.source)
        info = document_module.to_text(self.source, self.target)
        self.assertEqual(info["tables"], 1)
        self.assertIn("Outer", self.target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
