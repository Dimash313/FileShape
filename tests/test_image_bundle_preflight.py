"""Pre-decode PDF image batch input safety and pixel budget regressions.

All fixtures are generated in temporary directories as solid-color geometry.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from services import image_bundle, image_tools


class ImageBundlePreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first = self.root / "first.png"
        self.second = self.root / "second.png"
        Image.new("RGB", (60, 50), (30, 60, 90)).save(self.first)
        Image.new("RGBA", (40, 30), (80, 40, 20, 0)).save(self.second)
        self.target = self.root / "bundle.pdf"

    def assert_not_published(self):
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob(".fileshape_image_*")))

    def test_valid_bundle_still_preserves_page_count_and_order(self):
        self.assertEqual(image_bundle.images_to_pdf(
            [self.first, self.second], self.target
        ), 2)
        pages = PdfReader(self.target).pages
        self.assertEqual(len(pages), 2)
        # Dimensions reflect 96 DPI, preserving the existing renderer.
        self.assertGreater(float(pages[0].mediabox.width),
                           float(pages[1].mediabox.width))
        self.assertFalse(list(self.root.glob(".fileshape_image_*")))

    def test_first_header_over_budget_rejects_without_decoding(self):
        with patch.object(image_bundle, "MAX_BUNDLE_PIXELS", 100):
            with patch.object(image_bundle, "_open_image",
                              side_effect=AssertionError("decoded before preflight")):
                with self.assertRaisesRegex(ValueError, "разрешение"):
                    image_bundle.images_to_pdf(
                        [self.first, self.second], self.target
                    )
        self.assert_not_published()

    def test_later_header_over_budget_rejects_before_first_decode(self):
        # First image fits (3,000 px); first + second (4,200 px) does not.
        with patch.object(image_bundle, "MAX_BUNDLE_PIXELS", 3500):
            with patch.object(image_bundle, "_open_image",
                              side_effect=AssertionError("decoded before preflight")) as decoder:
                with self.assertRaisesRegex(ValueError, "разрешение"):
                    image_bundle.images_to_pdf(
                        [self.first, self.second], self.target
                    )
                decoder.assert_not_called()
        self.assert_not_published()

    def test_individual_pixel_cap_applies_to_headers_before_decode(self):
        with patch.object(image_tools, "MAX_IMAGE_PIXELS", 2000):
            with patch.object(image_bundle, "_open_image",
                              side_effect=AssertionError("decoded before per-file check")):
                with self.assertRaisesRegex(ValueError, "dimensions"):
                    image_bundle.images_to_pdf(
                        [self.first, self.second], self.target
                    )
        self.assert_not_published()

    def test_too_many_source_bytes_rejected_without_parsing(self):
        with patch.object(image_bundle, "MAX_BUNDLE_BYTES", 1):
            with patch.object(Image, "open",
                              side_effect=AssertionError("parsed before byte budget")) as parse:
                with self.assertRaisesRegex(ValueError, "20 МБ"):
                    image_bundle.images_to_pdf(
                        [self.first, self.second], self.target
                    )
                parse.assert_not_called()
        self.assert_not_published()

    def test_symlink_source_rejected_before_pillow_open(self):
        link = self.root / "link.png"
        try:
            link.symlink_to(self.first)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with patch.object(Image, "open",
                          side_effect=AssertionError("opened a symlink")):
            with self.assertRaisesRegex(ValueError, "обычные файлы"):
                image_bundle.images_to_pdf([self.second, link], self.target)
        self.assert_not_published()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires POSIX")
    def test_fifo_source_rejected_without_blocking(self):
        fifo = self.root / "pipe.png"
        os.mkfifo(fifo)
        with patch.object(Image, "open",
                          side_effect=AssertionError("opened a FIFO")):
            with self.assertRaisesRegex(ValueError, "обычные файлы"):
                image_bundle.images_to_pdf([self.first, fifo], self.target)
        self.assert_not_published()

    def test_corrupt_later_header_stops_before_any_decode(self):
        corrupt = self.root / "corrupt.png"
        corrupt.write_bytes(b"not a valid PNG or supported image")
        with patch.object(image_bundle, "_open_image",
                          side_effect=AssertionError("started decode")) as decoder:
            with self.assertRaises((OSError, ValueError)):
                image_bundle.images_to_pdf([self.first, corrupt], self.target)
            decoder.assert_not_called()
        self.assert_not_published()

    def test_changed_dimensions_after_preflight_rechecked(self):
        inflated = Image.new("RGB", (100, 100), "white")
        self.addCleanup(inflated.close)
        with patch.object(image_bundle, "MAX_BUNDLE_PIXELS", 4200):
            with patch.object(image_bundle, "_open_image", return_value=inflated) as decode:
                with self.assertRaisesRegex(ValueError, "разрешение"):
                    image_bundle.images_to_pdf([self.first, self.second], self.target)
                decode.assert_called_once()
                self.assertTrue(hasattr(decode.call_args.args[0], "fileno"))
        self.assert_not_published()

    def test_preflight_failure_preserves_existing_target(self):
        previous = b"existing PDF must remain intact"
        self.target.write_bytes(previous)
        with patch.object(image_bundle, "MAX_BUNDLE_PIXELS", 100):
            with self.assertRaises(ValueError):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertFalse(list(self.root.glob(".fileshape_image_*")))


if __name__ == "__main__":
    unittest.main()
