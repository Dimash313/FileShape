"""Release transient image buffers before decoding the next PDF page.

All fixtures are generated solid colors; no external media is used.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from services import image_bundle
from services.image_module import image_module


class ImageBundleTransientReleaseTests(unittest.TestCase):
    def setUp(self):
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        self.root = Path(workdir.name)
        self.rgb = self.root / "first.png"
        self.transparent = self.root / "second.png"
        self.last = self.root / "third.webp"
        self.target = self.root / "joined.pdf"
        Image.new("RGB", (30, 20), (40, 50, 70)).save(self.rgb)
        Image.new("RGBA", (40, 32), (90, 120, 140, 80)).save(self.transparent)
        Image.new("RGB", (20, 24), (70, 110, 50)).save(self.last)

    def assert_closed(self, image):
        with self.assertRaisesRegex(ValueError, "closed image"):
            image.getpixel((0, 0))

    def assert_no_stages(self):
        self.assertEqual(list(self.root.glob(".fileshape_image_*")), [])

    def test_decoded_original_closed_before_decoding_next_member(self):
        opened = []
        original = image_bundle._open_image

        def track_next(stream):
            if opened:
                self.assert_closed(opened[-1])
            result = original(stream)
            opened.append(result)
            return result

        with patch.object(image_bundle, "_open_image", side_effect=track_next):
            self.assertEqual(
                image_module.bundle_as_pdf(
                    [self.rgb, self.transparent, self.last], self.target,
                ), 3,
            )

        self.assertEqual(len(opened), 3)
        for image in opened:
            self.assert_closed(image)
        self.assertEqual(
            [float(page.mediabox.width) for page in PdfReader(self.target).pages],
            [22.5, 30.0, 15.0],
        )
        self.assert_no_stages()

    def test_transient_rgba_copy_closed_before_next_member(self):
        transient_copies = []
        original_convert = Image.Image.convert
        original_decode = image_bundle._open_image

        def inspect_convert(image, mode=None, *args, **kwargs):
            result = original_convert(image, mode, *args, **kwargs)
            if mode == "RGBA":
                transient_copies.append(result)
            return result

        def inspect_decode(stream):
            if transient_copies:
                self.assert_closed(transient_copies[-1])
            return original_decode(stream)

        with patch.object(
            Image.Image, "convert", autospec=True, side_effect=inspect_convert,
        ), patch.object(image_bundle, "_open_image", side_effect=inspect_decode):
            self.assertEqual(
                image_bundle.images_to_pdf(
                    [self.transparent, self.last], self.target,
                ), 2,
            )
        self.assertGreaterEqual(len(transient_copies), 1)
        for image in transient_copies:
            self.assert_closed(image)
        self.assertEqual(len(PdfReader(self.target).pages), 2)
        self.assert_no_stages()

    def test_transparency_paste_failure_closes_allocated_canvas(self):
        previous = b"original result stays valid"
        self.target.write_bytes(previous)
        allocated = []
        real_new = Image.new

        def tracked_new(*args, **kwargs):
            image = real_new(*args, **kwargs)
            allocated.append(image)
            return image

        with patch.object(Image, "new", side_effect=tracked_new), patch.object(
            Image.Image, "paste", side_effect=OSError("injected paste failure"),
        ):
            with self.assertRaisesRegex(OSError, "paste failure"):
                image_bundle.images_to_pdf(
                    [self.transparent, self.last], self.target,
                )

        self.assertTrue(allocated)
        for image in allocated:
            self.assert_closed(image)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assert_no_stages()

    def test_late_invalid_member_does_not_damage_existing_pdf(self):
        self.target.write_bytes(b"existing result")
        corrupt = self.root / "corrupt.webp"
        corrupt.write_bytes(b"invalid image")
        with self.assertRaises((OSError, ValueError)):
            image_bundle.images_to_pdf(
                [self.rgb, self.transparent, corrupt], self.target,
            )
        self.assertEqual(self.target.read_bytes(), b"existing result")
        self.assert_no_stages()


if __name__ == "__main__":
    unittest.main()
