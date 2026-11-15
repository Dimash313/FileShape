"""Negative real-file PDF regression tests for the existing bounded domain port."""
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from services.pdf_module import pdf_module
from services.pdf_tools import MAX_PDF_PAGES


def make_pdf(path: Path, pages: int, *, password: str | None = None) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password is not None:
        writer.encrypt(password)
    with path.open("wb") as output:
        writer.write(output)


class PdfSafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_truncated_pdf_rejected_without_output(self):
        source = self.root / "truncated.pdf"
        source.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\n")
        target = self.root / "result.pdf"
        with self.assertRaises(Exception):
            pdf_module.extract(source, target, "1")
        self.assertFalse(target.exists())

    def test_encrypted_pdf_rejected_without_output(self):
        source = self.root / "encrypted.pdf"
        make_pdf(source, 1, password="private")
        target = self.root / "result.pdf"
        with self.assertRaisesRegex(ValueError, "Password-protected"):
            pdf_module.rotate(source, target, 90)
        self.assertFalse(target.exists())

    def test_page_limit_rejected_without_output(self):
        source = self.root / "too_many.pdf"
        make_pdf(source, MAX_PDF_PAGES + 1)
        target = self.root / "result.pdf"
        with self.assertRaisesRegex(ValueError, "too many pages"):
            pdf_module.extract(source, target, "1")
        self.assertFalse(target.exists())

    def test_merge_total_page_limit_rejected_without_output(self):
        first = self.root / "first.pdf"
        second = self.root / "second.pdf"
        make_pdf(first, MAX_PDF_PAGES)
        make_pdf(second, 1)
        target = self.root / "merged.pdf"
        with self.assertRaisesRegex(ValueError, "Combined PDF exceeds page limit"):
            pdf_module.merge([first, second], target)
        self.assertFalse(target.exists())

    def test_valid_pdf_still_extracts(self):
        source = self.root / "valid.pdf"
        target = self.root / "result.pdf"
        make_pdf(source, 2)
        self.assertEqual(pdf_module.extract(source, target, "2"), 1)
        self.assertEqual(pdf_module.count_pages(target), 1)


if __name__ == "__main__":
    unittest.main()
