"""Pinned image-source descriptors: prevent path replacement across preflight/decode.

All fixtures are synthetic solid-color geometry. No external image assets.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from services import image_bundle, image_tools
from services.image_module import image_module


class PinnedImageSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first = self.root / "first.png"
        self.second = self.root / "second.png"
        Image.new("RGB", (32, 16), "blue").save(self.first)
        Image.new("RGBA", (12, 20), (50, 80, 100, 0)).save(self.second)
        self.output = self.root / "pages.pdf"

    def assert_clean(self):
        self.assertFalse(list(self.root.glob(".fileshape_image_*")))

    def test_replacement_by_another_regular_file_does_not_bypass_preflight(self):
        """A passed header cannot be replaced with unapproved file contents."""
        replacement = self.root / "replacement.png"
        # A disguised GIF is not an approved source type.
        Image.new("RGB", (120, 40), "red").save(replacement, format="GIF")
        validator = image_tools._validate_image_input_header
        checks = 0

        def swap_after_second_header(image):
            nonlocal checks
            validator(image)
            checks += 1
            if checks == 2:
                os.replace(replacement, self.first)

        with patch.object(
            image_tools, "_validate_image_input_header", side_effect=swap_after_second_header
        ):
            self.assertEqual(
                image_module.bundle_as_pdf([self.first, self.second], self.output), 2
            )
        self.assertEqual(checks, 4)  # two header checks + two decoding checks
        self.assertEqual(len(PdfReader(self.output).pages), 2)
        with Image.open(self.first) as changed:
            self.assertEqual(changed.format, "GIF")
        # The PDF's first page still has the original 32px width, not 120px.
        widths = [float(p.mediabox.width) for p in PdfReader(self.output).pages]
        self.assertEqual(widths, [24.0, 9.0])
        self.assert_clean()

    def test_single_image_decode_rejects_symlink(self):
        outside = self.root / "original.png"
        Image.new("RGB", (20, 20), "green").save(outside)
        link = self.root / "link.png"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "обычные файлы"):
            image_module.convert(link, self.root / "output.webp", "WEBP")
        self.assertFalse((self.root / "output.webp").exists())
        self.assert_clean()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX-only FIFO test")
    def test_single_image_fifo_rejected_without_read_block(self):
        fifo = self.root / "named_pipe.png"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "обычные файлы"):
            image_module.compress(fifo, self.root / "output.webp")
        self.assertFalse((self.root / "output.webp").exists())
        self.assert_clean()

    def test_headers_and_decoder_share_original_open_stream(self):
        inspected = []
        real_decode = image_bundle._open_image

        def inspect_and_decode(stream):
            self.assertFalse(stream.closed)
            self.assertTrue(hasattr(stream, "fileno"))
            old_offset = stream.tell()
            stream.seek(0)
            inspected.append((os.fstat(stream.fileno()).st_ino, stream.read(8)))
            stream.seek(old_offset)
            return real_decode(stream)

        with patch.object(image_bundle, "_open_image", side_effect=inspect_and_decode):
            self.assertEqual(
                image_bundle.images_to_pdf([self.first, self.second], self.output), 2
            )
        self.assertEqual(len(inspected), 2)
        self.assertTrue(all(signature == bytes((137, 80, 78, 71, 13, 10, 26, 10)) for _, signature in inspected))
        self.assert_clean()

    def test_bad_later_header_leaves_no_results(self):
        corrupt = self.root / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        with patch.object(
            image_bundle, "_open_image", side_effect=AssertionError("unexpected decode")
        ) as decoder:
            with self.assertRaises((OSError, ValueError)):
                image_bundle.images_to_pdf([self.first, corrupt], self.output)
            decoder.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "Linux FD inspection")
    def test_no_source_descriptor_leak_after_repeated_preflight_failures(self):
        corrupt = self.root / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        before = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(15):
            with self.assertRaises((OSError, ValueError)):
                image_bundle.images_to_pdf([self.first, corrupt], self.output)
        after = len(list(Path("/proc/self/fd").iterdir()))
        self.assertEqual(before, after)
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
