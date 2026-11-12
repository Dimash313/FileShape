"""Regression tests for image bundles and input safety limits."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from services.image_bundle import images_to_pdf


class ImageBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def make_image(self, name, mode="RGB", color="blue", size=(24, 16)):
        path = self.folder / name
        Image.new(mode, size, color).save(path)
        return path

    def test_multipage_pdf_order(self):
        first = self.make_image("first.png", "RGB", "blue", (24, 16))
        second = self.make_image("second.webp", "RGBA", (10, 20, 30, 0), (12, 18))
        target = self.folder / "result.pdf"
        self.assertEqual(images_to_pdf([first, second], target), 2)
        pages = PdfReader(target).pages
        self.assertEqual(len(pages), 2)
        self.assertNotEqual(pages[0].mediabox.width, pages[1].mediabox.width)

    def test_reject_wrong_count(self):
        path = self.make_image("one.png")
        with self.assertRaises(ValueError):
            images_to_pdf([path], self.folder / "fail.pdf")
        with self.assertRaises(ValueError):
            images_to_pdf([path] * 9, self.folder / "fail.pdf")

    def test_reject_invalid_image_and_excess_pixels(self):
        first = self.make_image("one.png")
        invalid = self.folder / "bad.png"
        invalid.write_bytes(b"invalid")
        with self.assertRaises(Exception):
            images_to_pdf([first, invalid], self.folder / "invalid.pdf")
        big = self.make_image("large.png", size=(5000, 5000))
        with self.assertRaises(ValueError):
            images_to_pdf([first, big], self.folder / "too_large.pdf")


if __name__ == "__main__":
    unittest.main()
