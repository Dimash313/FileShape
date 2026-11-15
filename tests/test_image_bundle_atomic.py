"""Multi-image PDF publication and failure-cleanup regressions.

Uses synthetic geometric images only; no external assets or network.
"""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from services import image_bundle, image_tools
from services.image_module import image_module


class ImageBundleAtomicOutputTests(unittest.TestCase):
    def setUp(self):
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        self.directory = Path(workdir.name)
        self.first = self.directory / "first.png"
        self.second = self.directory / "second.png"
        Image.new("RGB", (24, 16), (0, 0, 255)).save(self.first)
        Image.new("RGBA", (12, 18), (120, 90, 30, 0)).save(self.second)
        self.target = self.directory / "bundle.pdf"

    def assert_no_stages(self):
        self.assertEqual(list(self.directory.glob(".fileshape_image_*.tmp")), [])

    def test_real_pdf_has_two_pages_in_order(self):
        self.assertEqual(
            image_module.bundle_as_pdf([self.first, self.second], self.target), 2
        )
        pages = PdfReader(self.target).pages
        self.assertEqual(len(pages), 2)
        self.assertEqual(
            [float(page.mediabox.width) for page in pages], [18.0, 9.0]
        )
        self.assert_no_stages()

    def test_complete_result_replaces_previous_output(self):
        self.target.write_bytes(b"old pdf placeholder")
        self.assertEqual(image_bundle.images_to_pdf([self.first, self.second], self.target), 2)
        self.assertEqual(len(PdfReader(self.target).pages), 2)
        self.assert_no_stages()

    def test_partial_encode_error_preserves_previous_pdf(self):
        previous = b"prior complete output"
        self.target.write_bytes(previous)

        def partially_fail(_image, filename, **_kwargs):
            Path(filename).write_bytes(b"%PDF-1.4\npartial pdf")
            raise OSError("injected PDF encoder failure")

        with patch.object(Image.Image, "save", autospec=True, side_effect=partially_fail):
            with self.assertRaisesRegex(OSError, "encoder failure"):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assert_no_stages()

    def test_partial_encode_error_does_not_publish_absent_target(self):
        def partially_fail(_image, filename, **_kwargs):
            Path(filename).write_bytes(b"partial")
            raise OSError("encode interruption")

        with patch.object(Image.Image, "save", autospec=True, side_effect=partially_fail):
            with self.assertRaisesRegex(OSError, "interruption"):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_stages()

    def test_failed_publish_does_not_clobber_original_or_leave_stage(self):
        previous = b"retain output"
        self.target.write_bytes(previous)
        with patch.object(image_tools.os, "replace", side_effect=OSError("rename denied")):
            with self.assertRaisesRegex(OSError, "rename denied"):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assert_no_stages()

    def test_replacing_symlink_does_not_modify_external_target(self):
        external = self.directory / "important.txt"
        external.write_bytes(b"keep intact")
        try:
            self.target.symlink_to(external)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"filesystem does not support symlinks: {error}")
        self.assertEqual(image_bundle.images_to_pdf([self.first, self.second], self.target), 2)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(external.read_bytes(), b"keep intact")
        self.assertEqual(len(PdfReader(self.target).pages), 2)
        self.assert_no_stages()

    def test_rejected_count_corrupt_input_and_byte_limit_leave_no_result(self):
        with self.assertRaises(ValueError):
            image_bundle.images_to_pdf([self.first], self.target)
        with self.assertRaises(ValueError):
            image_bundle.images_to_pdf([self.first] * 9, self.target)
        corrupt = self.directory / "broken.png"
        corrupt.write_bytes(b"not a real image")
        with self.assertRaises((OSError, ValueError)):
            image_bundle.images_to_pdf([self.first, corrupt], self.target)
        with patch.object(image_bundle, "MAX_BUNDLE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "20 МБ"):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_stages()

    def test_cumulative_pixel_budget_rejected_without_publishing(self):
        with patch.object(image_bundle, "MAX_BUNDLE_PIXELS", 500):
            with self.assertRaisesRegex(ValueError, "разрешение"):
                image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertFalse(self.target.exists())
        self.assert_no_stages()

    @unittest.skipUnless(os.name == "posix", "POSIX file-permission check")
    def test_output_file_remains_private(self):
        image_bundle.images_to_pdf([self.first, self.second], self.target)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assert_no_stages()


if __name__ == "__main__":
    unittest.main()
