"""Regression checks for extracting PDF logic into a separate domain module.

Legacy API and Telegram imports must continue working while the actual PDF
implementation stays independent from image and ingress infrastructure.
"""
import ast
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pypdf import PdfReader, PdfWriter

from services import file_tools, pdf_tools
from services.pdf_module import pdf_module


ROOT = Path(__file__).resolve().parents[1]


def make_pdf(target: Path, page_count: int) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=120, height=180)
    with target.open("wb") as stream:
        writer.write(stream)


class PdfExtractionBoundaryTests(unittest.TestCase):
    def test_existing_imports_are_the_same_function_objects(self):
        names = (
            "pdf_page_count",
            "parse_page_selection",
            "extract_pdf_pages",
            "rotate_pdf",
            "merge_pdfs",
            "remove_pdf_pages",
            "_reader",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIs(getattr(file_tools, name), getattr(pdf_tools, name))
                self.assertEqual(
                    getattr(file_tools, name).__module__,
                    "services.pdf_tools",
                )
        for name in ("MAX_PDF_PAGES", "MAX_MERGE_FILES", "MAX_SELECTED_PAGES"):
            with self.subTest(name=name):
                self.assertEqual(getattr(file_tools, name), getattr(pdf_tools, name))

    def test_pdf_implementation_has_no_image_or_ingress_imports(self):
        code = (ROOT / "services" / "pdf_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        for imported in modules:
            with self.subTest(imported=imported):
                self.assertNotEqual(imported.split(".")[0], "PIL")
                self.assertNotEqual(imported, "services.file_tools")
                self.assertNotEqual(imported, "services.image_tools")
                self.assertFalse(imported.startswith(("api", "main", "aiogram", "fastapi")))
        # PDF functions are implemented only in pdf_tools, not duplicated in
        # the backwards-compatibility file used by legacy call sites.
        legacy = ast.parse(
            (ROOT / "services" / "file_tools.py").read_text(encoding="utf-8")
        )
        legacy_defs = {node.name for node in legacy.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertFalse(
            legacy_defs.intersection({
                "pdf_page_count", "parse_page_selection", "extract_pdf_pages",
                "rotate_pdf", "merge_pdfs", "remove_pdf_pages", "_reader",
            })
        )

    def test_legacy_pdf_import_and_typed_module_produce_same_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            second = root / "second.pdf"
            make_pdf(source, 4)
            make_pdf(second, 2)

            self.assertEqual(file_tools.pdf_page_count(source), 4)
            self.assertEqual(pdf_module.count_pages(source), 4)
            self.assertEqual(file_tools.parse_page_selection("4,1-2", 4), [3, 0, 1])
            output = root / "selected.pdf"
            self.assertEqual(pdf_module.extract(source, output, "4,1-2"), 3)
            self.assertEqual(len(PdfReader(str(output)).pages), 3)
            merged = root / "merged.pdf"
            self.assertEqual(file_tools.merge_pdfs([source, second], merged), 6)
            self.assertEqual(pdf_module.count_pages(merged), 6)
            with self.assertRaises(ValueError):
                file_tools.remove_pdf_pages(source, root / "invalid.pdf", "1-4")

    def test_image_tools_still_work_without_pdf_domain_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            jpg = root / "converted.jpg"
            webp = root / "optimized.webp"
            Image.new("RGB", (16, 12), (15, 85, 170)).save(source)
            file_tools.convert_image(source, jpg, "JPEG")
            file_tools.compress_image(source, webp)
            with Image.open(jpg) as result:
                self.assertEqual(result.format, "JPEG")
                self.assertEqual(result.size, (16, 12))
            with Image.open(webp) as result:
                self.assertEqual(result.format, "WEBP")
                self.assertEqual(result.size, (16, 12))


if __name__ == "__main__":
    unittest.main()
