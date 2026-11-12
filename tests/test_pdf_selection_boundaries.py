"""Boundary and regression checks for PDF page selection and real PDF edits."""
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from services.file_tools import (
    extract_pdf_pages,
    parse_page_selection,
    pdf_page_count,
    remove_pdf_pages,
)


def make_pdf(path: Path, count: int) -> None:
    writer = PdfWriter()
    for index in range(count):
        # Distinct widths let tests verify ordering and preservation.
        writer.add_blank_page(width=100 + index, height=200)
    with path.open("wb") as output:
        writer.write(output)


class PdfSelectionBoundaryTests(unittest.TestCase):
    def test_valid_ranges_preserve_order_and_deduplicate(self):
        cases = {
            "1": [0],
            "1,3": [0, 2],
            "1,3-5": [0, 2, 3, 4],
            " 1 , 3 - 5 ": [0, 2, 3, 4],
            "3,1,3,2": [2, 0, 1],
            "1-3,2-4": [0, 1, 2, 3],
            "6": [5],
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_page_selection(value, 6), expected)

    def test_invalid_page_ranges(self):
        invalid = (
            "", " ", "0", "7", "1-7", "4-2", "1,,2", ",1",
            "1,", "1--2", "-2", "1;2", "a", "1.5", "1_2",
            "1-2-3", "1,0", "2,7", "1\n2", "1" * 91,
        )
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    parse_page_selection(value, 6)

    def test_selection_limits(self):
        self.assertEqual(len(parse_page_selection("1-150", 250)), 150)
        with self.assertRaises(ValueError):
            parse_page_selection("1-151", 250)
        with self.assertRaises(ValueError):
            parse_page_selection("1-100,101-151", 250)
        for total in (0, 251):
            with self.subTest(total=total):
                with self.assertRaises(ValueError):
                    parse_page_selection("1", total)

    def test_extract_order_and_remove_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            extracted = Path(directory) / "extract.pdf"
            removed = Path(directory) / "remove.pdf"
            make_pdf(source, 6)
            self.assertEqual(extract_pdf_pages(source, extracted, "5,1,3-4"), 4)
            widths = [int(page.mediabox.width) for page in PdfReader(str(extracted)).pages]
            self.assertEqual(widths, [104, 100, 102, 103])
            self.assertEqual(remove_pdf_pages(source, removed, "2,4-5"), 3)
            self.assertEqual(pdf_page_count(removed), 3)
            self.assertEqual(
                [int(page.mediabox.width) for page in PdfReader(str(removed)).pages],
                [100, 102, 105],
            )
            with self.assertRaisesRegex(ValueError, "Нельзя удалить все"):
                remove_pdf_pages(source, removed, "1-6")


if __name__ == "__main__":
    unittest.main()
