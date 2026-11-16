"""Physical image-module extraction: compatibility and dependency regressions."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from services import file_tools, image_tools
from services.image_bundle import images_to_pdf
from services.image_module import image_module


ROOT = Path(__file__).resolve().parents[1]


class ImageExtractionTests(unittest.TestCase):
    def test_old_imports_resolve_to_new_implementation(self):
        for symbol in (
            "convert_image", "compress_image", "_open_image",
            "IMAGE_FORMATS", "MAX_IMAGE_PIXELS",
        ):
            with self.subTest(symbol=symbol):
                self.assertIs(getattr(file_tools, symbol),
                              getattr(image_tools, symbol))
        for symbol in ("_open_image", "convert_image", "compress_image"):
            self.assertEqual(getattr(file_tools, symbol).__module__,
                             "services.image_tools")

    def test_image_implementation_has_no_pdf_or_telegram_dependencies(self):
        code = (ROOT / "services" / "image_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        for module in imported:
            with self.subTest(module=module):
                self.assertFalse(module == "pypdf" or module.startswith("pypdf."))
                self.assertFalse(module == "services.pdf_tools")
                self.assertFalse(module == "services.file_tools")
                self.assertFalse(module == "api" or module.startswith("api."))
                self.assertFalse(module == "aiogram" or module.startswith("aiogram."))
                self.assertFalse(module == "fastapi" or module.startswith("fastapi."))
        legacy = ast.parse(
            (ROOT / "services" / "file_tools.py").read_text(encoding="utf-8")
        )
        self.assertFalse(
            any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                for n in legacy.body),
            "Legacy facade must not duplicate image or PDF algorithms",
        )

    def test_multi_image_pdf_builder_uses_image_domain_not_legacy_facade(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "a.png"
            second = root / "b.png"
            Image.new("RGB", (20, 10), "white").save(first)
            Image.new("RGB", (10, 20), "blue").save(second)
            result = root / "output.pdf"
            with patch.object(
                file_tools, "_open_image",
                side_effect=AssertionError("legacy facade should not run"),
            ):
                self.assertEqual(images_to_pdf([first, second], result), 2)
            self.assertEqual(len(PdfReader(str(result)).pages), 2)

    def test_pdf_impl_and_image_adapter_are_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "photo.png"
            Image.new("RGB", (11, 13), "green").save(source)
            output = root / "converted.png"
            with patch.object(
                file_tools, "convert_image",
                side_effect=AssertionError("legacy facade should not run"),
            ):
                image_module.convert(source, output, "PNG")
            with Image.open(output) as decoded:
                self.assertEqual(decoded.format, "PNG")
                self.assertEqual(decoded.size, (11, 13))

    def test_image_bundle_imports_domain_directly(self):
        tree = ast.parse(
            (ROOT / "services" / "image_bundle.py").read_text(encoding="utf-8")
        )
        imports = [(node.module, [item.name for item in node.names])
                   for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom)]
        # Adding another image-domain helper must not fail this boundary
        # test: check where the symbol is imported from, not the entire list.
        self.assertTrue(any(
            module == "services.image_tools" and "_open_image" in names
            for module, names in imports
        ))
        self.assertFalse(any(
            module == "services.file_tools" and "_open_image" in names
            for module, names in imports
        ))


if __name__ == "__main__":
    unittest.main()
