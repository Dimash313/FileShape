"""Real image-parser preflight tests for supported inputs and frame counts.

Synthetic geometric/solid-color fixtures only. No external data or assets.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from services import image_bundle, image_tools
from services.image_module import image_module


class ImageInputFormatPreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.other = self.root / "other.png"
        Image.new("RGBA", (18, 13), (50, 60, 70, 0)).save(self.other)

    def assert_no_stages(self):
        self.assertFalse(list(self.root.glob(".fileshape_image_*")))

    def make_image(self, suffix: str, fmt: str):
        source = self.root / ("input" + suffix)
        Image.new("RGB", (18, 13), (30, 90, 150)).save(source, format=fmt)
        return source

    def test_real_jpeg_png_webp_inputs_still_convert_and_compress(self):
        for suffix, fmt in ((".jpg", "JPEG"), (".png", "PNG"), (".webp", "WEBP")):
            with self.subTest(source=fmt):
                source = self.make_image(suffix, fmt)
                target = self.root / "converted.png"
                image_module.convert(source, target, "PNG")
                with Image.open(target) as result:
                    self.assertEqual(result.format, "PNG")
                    self.assertEqual(result.size, (18, 13))
                optimized = self.root / "optimized.webp"
                image_module.compress(source, optimized)
                with Image.open(optimized) as result:
                    self.assertEqual(result.format, "WEBP")
                self.assert_no_stages()

    def test_supported_content_with_misleading_suffix_remains_supported(self):
        source = self.make_image(".png", "JPEG")
        target = self.root / "result.webp"
        image_module.convert(source, target, "WEBP")
        with Image.open(target) as result:
            self.assertEqual(result.format, "WEBP")
        self.assert_no_stages()

    def test_disguised_gif_and_tiff_are_rejected_for_single_image_operations(self):
        for fmt in ("GIF", "TIFF"):
            with self.subTest(actual_format=fmt):
                source = self.make_image(".png", fmt)
                target = self.root / "result.png"
                target.write_bytes(b"existing result")
                for action in ("convert", "compress"):
                    with self.subTest(action=action):
                        with self.assertRaisesRegex(ValueError, "Unsupported image input format"):
                            if action == "convert":
                                image_module.convert(source, target, "PNG")
                            else:
                                image_module.compress(source, target)
                        self.assertEqual(target.read_bytes(), b"existing result")
                        self.assert_no_stages()

    def test_unsupported_format_in_later_batch_fails_before_decode(self):
        hidden = self.make_image(".png", "GIF")
        target = self.root / "bundle.pdf"
        with patch.object(
            image_bundle, "_open_image",
            side_effect=AssertionError("decoded a previous image before header pass"),
        ) as decoder:
            with self.assertRaisesRegex(ValueError, "Unsupported image input format"):
                image_module.bundle_as_pdf([self.other, hidden], target)
            decoder.assert_not_called()
        self.assertFalse(target.exists())
        self.assert_no_stages()

    def make_animation(self, fmt: str):
        source = self.root / ("animated." + fmt.lower())
        first = Image.new("RGBA", (18, 13), (70, 80, 90, 255))
        second = Image.new("RGBA", (18, 13), (30, 40, 50, 255))
        try:
            first.save(
                source, format=fmt, save_all=True, append_images=[second],
                duration=100, loop=0,
            )
        finally:
            first.close()
            second.close()
        with Image.open(source) as verify:
            self.assertGreater(verify.n_frames, 1)
        return source

    def test_multiframe_webp_and_apng_rejected_before_single_image_decode(self):
        for fmt in ("WEBP", "PNG"):
            with self.subTest(animation=fmt):
                source = self.make_animation(fmt)
                target = self.root / "converted.jpg"
                for action in ("convert", "compress"):
                    with self.subTest(action=action):
                        with self.assertRaisesRegex(ValueError, "Multi-frame images"):
                            if action == "convert":
                                image_module.convert(source, target, "JPEG")
                            else:
                                image_module.compress(source, target)
                        self.assertFalse(target.exists())
                        self.assert_no_stages()

    def test_animated_later_batch_item_fails_before_any_decode(self):
        source = self.make_animation("WEBP")
        target = self.root / "bundle.pdf"
        with patch.object(image_bundle, "_open_image", side_effect=AssertionError("decoded")) as decoder:
            with self.assertRaisesRegex(ValueError, "Multi-frame images"):
                image_module.bundle_as_pdf([self.other, source], target)
            decoder.assert_not_called()
        self.assertFalse(target.exists())
        self.assert_no_stages()

    def test_corrupt_input_does_not_publish_result(self):
        source = self.root / "broken.webp"
        source.write_bytes(b"RIFF?broken-file")
        target = self.root / "out.jpg"
        with self.assertRaises((OSError, ValueError)):
            image_module.convert(source, target, "JPEG")
        self.assertFalse(target.exists())
        self.assert_no_stages()


if __name__ == "__main__":
    unittest.main()
