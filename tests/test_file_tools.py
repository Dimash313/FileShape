"""Offline regression tests: no Telegram token required."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from services.file_tools import (
    compress_image,
    convert_image,
    extract_pdf_pages,
    merge_pdfs,
    parse_page_selection,
    pdf_page_count,
    rotate_pdf,
    remove_pdf_pages,
)


def blank_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with path.open("wb") as output:
        writer.write(output)


class FileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_page_selection(self):
        self.assertEqual(parse_page_selection("1,3-5,4", 6), [0, 2, 3, 4])
        for bad in ("0", "9", "3-2", "1,,2", "-3", "abc", "1;2"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_page_selection(bad, 6)

    def test_extract_and_rotate(self):
        original = self.dir / "original.pdf"
        extracted = self.dir / "extracted.pdf"
        rotated = self.dir / "rotated.pdf"
        blank_pdf(original, 4)
        self.assertEqual(pdf_page_count(original), 4)
        self.assertEqual(extract_pdf_pages(original, extracted, "2-3"), 2)
        self.assertEqual(len(PdfReader(str(extracted)).pages), 2)
        removed = self.dir / 'removed.pdf'
        self.assertEqual(remove_pdf_pages(original, removed, '2-3'), 2)
        self.assertEqual(pdf_page_count(removed), 2)
        with self.assertRaises(ValueError):
            remove_pdf_pages(original, removed, '1-4')
        self.assertEqual(rotate_pdf(original, rotated), 4)
        self.assertEqual(PdfReader(str(rotated)).pages[0].get("/Rotate"), 90)

    def test_merge_pdfs(self):
        a, b, result = (self.dir / name for name in ("a.pdf", "b.pdf", "merged.pdf"))
        blank_pdf(a, 2)
        blank_pdf(b, 3)
        self.assertEqual(merge_pdfs([a, b], result), 5)
        self.assertEqual(pdf_page_count(result), 5)

    def test_convert_and_optimize_image(self):
        source = self.dir / "input.png"
        jpg = self.dir / "out.jpg"
        webp = self.dir / "small.webp"
        pdf = self.dir / "image.pdf"
        Image.new("RGBA", (32, 32), (255, 0, 0, 0)).save(source)
        convert_image(source, jpg, "JPEG")
        compress_image(source, webp)
        convert_image(source, pdf, "PDF")
        self.assertEqual(pdf_page_count(pdf), 1)
        with Image.open(jpg) as output:
            self.assertEqual(output.format, "JPEG")
            self.assertTrue(all(pixel > 235 for pixel in output.getpixel((0, 0))))
        with Image.open(webp) as output:
            self.assertEqual(output.format, "WEBP")


if __name__ == "__main__":
    unittest.main()
