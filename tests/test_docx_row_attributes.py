"""Malformed DOCX row offset/merge attributes are rejected before text export."""
from pathlib import Path
import tempfile
import unittest

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from services.document_module import document_module


def row_offset(row, tag: str, value: str) -> None:
    """Set an OOXML gridBefore/gridAfter attribute, even if syntactically bad."""
    tr_pr = row._tr.get_or_add_trPr()
    element = OxmlElement("w:" + tag)
    element.set(qn("w:val"), value)
    tr_pr.append(element)


class MalformedRowAttributesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source.docx"
        self.target = self.root / "converted.txt"

    def assert_bad_table(self):
        with self.assertRaises(ValueError) as raised:
            document_module.to_text(self.source, self.target)
        self.assertEqual(str(raised.exception), "Повреждённая таблица DOCX")
        self.assertFalse(self.target.exists())

    def simple_table(self):
        doc = Document()
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "One"
        table.cell(0, 1).text = "Two"
        return doc, table

    def test_valid_plain_table_preserves_text(self):
        doc, _table = self.simple_table()
        doc.save(self.source)
        info = document_module.to_text(self.source, self.target)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "One\tTwo")
        self.assertEqual(info["tables"], 1)

    def test_valid_skipped_leading_and_trailing_grid_columns(self):
        doc = Document()
        table = doc.add_table(rows=2, cols=3)
        table.cell(0, 0).text = "A"
        table.cell(0, 1).text = "B"
        table.cell(0, 2).text = "C"
        table.cell(1, 1).text = "Middle"
        last = table.rows[1]._tr
        last.remove(last.tc_lst[2])
        last.remove(last.tc_lst[0])
        row_offset(table.rows[1], "gridBefore", "1")
        row_offset(table.rows[1], "gridAfter", "1")
        doc.save(self.source)
        document_module.to_text(self.source, self.target)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "A\tB\tC\nMiddle",
        )

    def test_invalid_grid_before_integer_is_normalized(self):
        doc, table = self.simple_table()
        row_offset(table.rows[0], "gridBefore", "not-an-integer")
        doc.save(self.source)
        self.assert_bad_table()

    def test_invalid_grid_after_integer_is_normalized(self):
        doc, table = self.simple_table()
        row_offset(table.rows[0], "gridAfter", "not-an-integer")
        doc.save(self.source)
        self.assert_bad_table()

    def test_negative_before_and_after_are_rejected(self):
        for tag in ("gridBefore", "gridAfter"):
            with self.subTest(tag=tag):
                doc, table = self.simple_table()
                row_offset(table.rows[0], tag, "-1")
                doc.save(self.source)
                self.assert_bad_table()

    def test_oversize_row_offset_is_rejected(self):
        doc, table = self.simple_table()
        row_offset(table.rows[0], "gridBefore", "100000000")
        doc.save(self.source)
        self.assert_bad_table()

    def test_offset_plus_expanded_cells_cannot_exceed_grid_width(self):
        doc, table = self.simple_table()
        row_offset(table.rows[0], "gridBefore", "1")
        doc.save(self.source)
        self.assert_bad_table()

    def test_unknown_vertical_merge_state_is_rejected(self):
        doc, table = self.simple_table()
        tc = table.rows[0]._tr.tc_lst[0]
        merge = tc.get_or_add_tcPr().get_or_add_vMerge()
        merge.set(qn("w:val"), "invalid-state")
        doc.save(self.source)
        self.assert_bad_table()

    def test_nested_table_invalid_offset_is_rejected(self):
        doc = Document()
        outer = doc.add_table(rows=1, cols=1)
        inner = outer.cell(0, 0).add_table(rows=1, cols=1)
        row_offset(inner.rows[0], "gridAfter", "broken")
        doc.save(self.source)
        self.assert_bad_table()


if __name__ == "__main__":
    unittest.main()
