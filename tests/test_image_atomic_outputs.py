"""Image results must be complete before publication in any supported format."""
from pathlib import Path
import os
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image

from services import image_tools
from services.image_module import image_module


class ImageAtomicOutputTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "input.png"
        # Geometry only: neutral translucent test fixture.
        Image.new("RGBA", (22, 15), (20, 60, 110, 0)).save(self.source)

    def assert_no_stage(self):
        self.assertEqual(list(self.root.glob(".fileshape_image_*")), [])

    def test_all_supported_formats_publish_valid_results(self):
        for fmt, extension in (
            ("JPEG", ".jpg"), ("PNG", ".png"),
            ("WEBP", ".webp"), ("PDF", ".pdf"),
        ):
            with self.subTest(fmt=fmt):
                target = self.root / ("result" + extension)
                image_module.convert(self.source, target, fmt)
                self.assertGreater(target.stat().st_size, 0)
                if fmt == "PDF":
                    self.assertTrue(target.read_bytes().startswith(b"%PDF"))
                else:
                    with Image.open(target) as decoded:
                        self.assertEqual(decoded.format, fmt)
                        self.assertEqual(decoded.size, (22, 15))
                        if fmt == "JPEG":
                            self.assertTrue(all(value > 230 for value in decoded.getpixel((0, 0))))
                self.assert_no_stage()

        compressed = self.root / "optimized.webp"
        image_module.compress(self.source, compressed)
        with Image.open(compressed) as decoded:
            self.assertEqual(decoded.format, "WEBP")
            self.assertEqual(decoded.size, (22, 15))
        self.assert_no_stage()

    def test_oversized_header_fails_before_decode_without_result(self):
        # A small real PNG with modified dimensions; never allocate 36m pixels.
        data = bytearray(self.source.read_bytes())
        data[16:24] = struct.pack(">II", 6000, 6000)
        data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]) & 0xFFFFFFFF)
        oversized = self.root / "huge_header.png"
        oversized.write_bytes(data)
        target = self.root / "huge.jpg"
        with self.assertRaises((Image.DecompressionBombWarning, Image.DecompressionBombError, ValueError)):
            image_module.convert(oversized, target, "JPEG")
        self.assertFalse(target.exists())
        self.assert_no_stage()

    def test_encoder_partial_write_does_not_replace_preexisting_result(self):
        existing = b"previous valid output"
        for operation in ("JPEG", "PNG", "WEBP", "PDF", "compress"):
            with self.subTest(operation=operation):
                target = self.root / "existing.out"
                target.write_bytes(existing)

                def partial_write(_image, filename, **_kwargs):
                    Path(filename).write_bytes(b"partial invalid image")
                    raise OSError("simulated encoder failure")

                with patch.object(Image.Image, "save", autospec=True, side_effect=partial_write):
                    with self.assertRaisesRegex(OSError, "encoder failure"):
                        if operation == "compress":
                            image_module.compress(self.source, target)
                        else:
                            image_module.convert(self.source, target, operation)
                self.assertEqual(target.read_bytes(), existing)
                self.assert_no_stage()

    def test_failed_final_publication_preserves_target_and_cleans_stage(self):
        target = self.root / "previous.webp"
        target.write_bytes(b"original preserved")
        with patch.object(image_tools.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                image_module.compress(self.source, target)
        self.assertEqual(target.read_bytes(), b"original preserved")
        self.assert_no_stage()

    def test_symlink_destination_is_replaced_not_followed(self):
        external = self.root / "outside.txt"
        external.write_bytes(b"do not change this")
        target = self.root / "output.png"
        try:
            target.symlink_to(external)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        image_module.convert(self.source, target, "PNG")
        self.assertFalse(target.is_symlink())
        self.assertEqual(external.read_bytes(), b"do not change this")
        with Image.open(target) as image:
            self.assertEqual(image.size, (22, 15))
        self.assert_no_stage()

    @unittest.skipUnless(os.name == "posix", "POSIX staged file permissions")
    def test_private_final_output_permissions(self):
        output = self.root / "private.webp"
        image_module.compress(self.source, output)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assert_no_stage()

    def test_invalid_source_and_unsupported_format_leave_no_result(self):
        corrupt = self.root / "bad.png"
        corrupt.write_bytes(b"not an image")
        target = self.root / "no-result.png"
        with self.assertRaises((OSError, ValueError)):
            image_module.convert(corrupt, target, "PNG")
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, "Unsupported image format"):
            image_module.convert(self.source, target, "BAD")
        self.assertFalse(target.exists())
        self.assert_no_stage()


if __name__ == "__main__":
    unittest.main()
