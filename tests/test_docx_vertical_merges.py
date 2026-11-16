"""Bound vertical DOCX merge chains before python-docx recursively resolves cells."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from services import document_tools
from services.document_module import document_module


class VerticalMergeSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source.docx"
        self.output = self.root / "converted.txt"

    def assert_rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            document_module.to_text(self.source, self.output)
        self.assertFalse(self.output.exists())

    def make_long_vertical_merge(self, count):
        doc = Document()
        table = doc.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "Value"
        top = table.rows[0]._tr.tc_lst[0]
        top.get_or_add_tcPr().get_or_add_vMerge().val = "restart"
        next_row = deepcopy(table.rows[0]._tr)
        next_row.tc_lst[0].get_or_add_tcPr().get_or_add_vMerge().val = "continue"
        for _ in range(count - 1):
            table._tbl.append(deepcopy(next_row))
        doc.save(self.source)

    def test_small_valid_vertical_merge_preserves_text(self):
        doc = Document()
        table = doc.add_table(rows=3, cols=2)
        for index, row in enumerate(table.rows):
            row.cells[1].text = f"R{index}"
        table.cell(0, 0).merge(table.cell(2, 0)).text = "Top"
        doc.save(self.source)
        result = document_module.to_text(self.source, self.output)
        self.assertEqual(result["tables"], 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"),
                         "Top\tR0\nTop\tR1\nTop\tR2")

    def test_horizontal_and_vertical_merge_preserve_text(self):
        doc = Document()
        table = doc.add_table(rows=2, cols=3)
        table.cell(0, 0).merge(table.cell(1, 1)).text = "Merged"
        table.cell(0, 2).text = "A"
        table.cell(1, 2).text = "B"
        doc.save(self.source)
        document_module.to_text(self.source, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"),
                         "Merged\tMerged\tA\nMerged\tMerged\tB")

    def test_1100_row_continuation_rejected_before_recursion(self):
        self.make_long_vertical_merge(1100)
        document_tools.validate_docx(self.source)
        self.assert_rejected("Слишком длинное объединение")

    def test_explicit_depth_limit_blocks_next_row(self):
        self.make_long_vertical_merge(4)
        with patch.object(document_tools, "MAX_DOCX_VERTICAL_MERGE_ROWS", 3):
            self.assert_rejected("Слишком длинное объединение")

    def test_orphan_first_row_continuation_rejected(self):
        doc = Document()
        table = doc.add_table(rows=1, cols=1)
        table.rows[0]._tr.tc_lst[0].get_or_add_tcPr().get_or_add_vMerge().val = "continue"
        doc.save(self.source)
        self.assert_rejected("Повреждённая таблица")

    def test_span_mismatch_to_previous_row_rejected(self):
        doc = Document()
        table = doc.add_table(rows=2, cols=2)
        table.cell(1, 0).merge(table.cell(1, 1))
        table.rows[1]._tr.tc_lst[0].get_or_add_tcPr().get_or_add_vMerge().val = "continue"
        doc.save(self.source)
        self.assert_rejected("Повреждённая таблица")

    def test_vertical_chain_resets_on_unmerged_row(self):
        doc = Document()
        table = doc.add_table(rows=5, cols=1)
        table.cell(0, 0).merge(table.cell(1, 0)).text = "A"
        table.cell(2, 0).text = "B"
        table.cell(3, 0).merge(table.cell(4, 0)).text = "C"
        doc.save(self.source)
        with patch.object(document_tools, "MAX_DOCX_VERTICAL_MERGE_ROWS", 2):
            document_module.to_text(self.source, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "A\nA\nB\nC\nC")

    def test_skipped_leading_grid_column_continuation(self):
        doc = Document()
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 1).text = "Last column"
        bottom = table.rows[1]._tr
        bottom.remove(bottom.tc_lst[0])
        tr_pr = bottom.get_or_add_trPr()
        before = OxmlElement("w:gridBefore")
        before.set(qn("w:val"), "1")
        tr_pr.append(before)
        bottom.tc_lst[0].get_or_add_tcPr().get_or_add_vMerge().val = "continue"
        doc.save(self.source)
        document_module.to_text(self.source, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "\tLast column\nLast column")


if __name__ == "__main__":
    unittest.main()
