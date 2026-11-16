"""Image domain contract and API routing parity with existing transformations."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from api import server
from services import image_tools, image_bundle
from services.image_module import ExistingImageModule, ImageModulePort, image_module


class ImageModuleContractTests(unittest.TestCase):
    def test_adapter_implements_image_port(self):
        self.assertIsInstance(image_module, ImageModulePort)

    def test_adapter_delegates_arguments_and_failures(self):
        source = Path("/private/input.png")
        target = Path("/private/result.jpg")
        adapter = ExistingImageModule()
        with patch.object(image_tools, "convert_image") as convert:
            adapter.convert(source, target, "JPEG")
            convert.assert_called_once_with(source, target, "JPEG")
        with patch.object(image_tools, "compress_image") as compress:
            adapter.compress(source, target)
            compress.assert_called_once_with(source, target)
        with patch.object(image_bundle, "images_to_pdf", return_value=2) as bundle:
            self.assertEqual(adapter.bundle_as_pdf([source, target], target), 2)
            bundle.assert_called_once_with([source, target], target)
        with patch.object(image_tools, "convert_image",
                          side_effect=ValueError("bad format")):
            with self.assertRaisesRegex(ValueError, "bad format"):
                adapter.convert(source, target, "bad")

    def test_real_conversion_formats_and_transparency(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            Image.new("RGBA", (20, 12), (5, 20, 100, 0)).save(source)
            for fmt, suffix in (
                ("JPEG", ".jpg"), ("PNG", ".png"),
                ("WEBP", ".webp"), ("PDF", ".pdf"),
            ):
                with self.subTest(fmt=fmt):
                    target = root / ("result" + suffix)
                    image_module.convert(source, target, fmt)
                    self.assertGreater(target.stat().st_size, 0)
                    if fmt == "PDF":
                        self.assertEqual(len(PdfReader(str(target)).pages), 1)
                    else:
                        with Image.open(target) as decoded:
                            self.assertEqual(decoded.format, fmt)
                            self.assertEqual(decoded.size, (20, 12))
                            if fmt == "JPEG":
                                self.assertTrue(all(channel > 230
                                                    for channel in decoded.getpixel((0, 0))))
            optimized = root / "optimized.webp"
            image_module.compress(source, optimized)
            with Image.open(optimized) as decoded:
                self.assertEqual(decoded.format, "WEBP")
                self.assertEqual(decoded.size, (20, 12))

    def test_bad_image_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "fake.png"
            target = root / "result.jpg"
            source.write_bytes(b"not an image")
            with self.assertRaises((OSError, ValueError)):
                image_module.convert(source, target, "JPEG")
            self.assertFalse(target.exists())

    def test_unsupported_format_does_not_create_a_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            target = root / "output.bad"
            Image.new("RGB", (5, 5)).save(source)
            with self.assertRaisesRegex(ValueError, "Unsupported image format"):
                image_module.convert(source, target, "UNKNOWN")
            self.assertFalse(target.exists())

    def test_api_routes_all_image_actions_through_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            cases = (
                ("img:JPEG", "converted.jpg", "convert", "JPEG"),
                ("img:PNG", "converted.png", "convert", "PNG"),
                ("img:WEBP", "converted.webp", "convert", "WEBP"),
                ("img:PDF", "converted.pdf", "convert", "PDF"),
                ("img:compress", "optimized.webp", "compress", None),
            )
            for action, filename, method, fmt in cases:
                with self.subTest(action=action):
                    with patch.object(server, "image_module") as module:
                        output = server._transform(source, root, action, "")
                        self.assertEqual(output.name, filename)
                        self.assertEqual(output.parent, root)
                        if method == "convert":
                            module.convert.assert_called_once_with(source, output, fmt)
                            module.compress.assert_not_called()
                        else:
                            module.compress.assert_called_once_with(source, output)
                            module.convert.assert_not_called()

    def test_api_conversion_errors_propagate_without_fake_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(server, "image_module") as module:
                module.compress.side_effect = ValueError("bad image")
                with self.assertRaisesRegex(ValueError, "bad image"):
                    server._transform(root / "bad.webp", root, "img:compress", "")

    def test_image_action_catalog_unchanged(self):
        from api.conversion_catalog import SUPPORTED
        self.assertEqual(SUPPORTED["image"], {
            "img:JPEG", "img:PNG", "img:WEBP", "img:PDF", "img:compress",
        })


if __name__ == "__main__":
    unittest.main()
