"""PDF modular boundary: real-file, dispatch, and failure regression tests.

The module preserves the existing PDF parser and page limits while giving API
clients a stable in-process interface. No mock test claims to prove real PDF
fidelity; generated PDFs below exercise the real adapter.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from api import server
from services import pdf_tools
from services.pdf_module import ExistingPdfModule, PdfModulePort, pdf_module


def make_pdf(path: Path, count: int) -> None:
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=90, height=120)
    with path.open("wb") as stream:
        writer.write(stream)


class PdfModuleContractTests(unittest.TestCase):
    def test_adapter_conforms_to_pdf_port(self):
        self.assertIsInstance(pdf_module, PdfModulePort)

    def test_adapter_preserves_legacy_function_calls(self):
        adapter = ExistingPdfModule()
        src = Path("/private/source.pdf")
        dest = Path("/private/result.pdf")
        other = Path("/private/other.pdf")
        calls = (
            ("pdf_page_count", "count_pages", (src,), 4),
            ("extract_pdf_pages", "extract", (src, dest, "1,3"), 2),
            ("rotate_pdf", "rotate", (src, dest, 180), 4),
            ("merge_pdfs", "merge", ([src, other], dest), 7),
            ("remove_pdf_pages", "remove", (src, dest, "2"), 3),
        )
        for legacy, method, args, value in calls:
            with self.subTest(method=method):
                with patch.object(pdf_tools, legacy, return_value=value) as fn:
                    self.assertEqual(getattr(adapter, method)(*args), value)
                    fn.assert_called_once_with(*args)

    def test_adapter_propagates_validation_errors(self):
        src, dest = Path("/private/source.pdf"), Path("/private/result.pdf")
        with patch.object(pdf_tools, "extract_pdf_pages",
                          side_effect=ValueError("Invalid page range")):
            with self.assertRaisesRegex(ValueError, "Invalid page range"):
                pdf_module.extract(src, dest, "5-1")

    def test_real_pdf_roundtrip_and_page_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "source.pdf"
            second = directory / "second.pdf"
            make_pdf(source, 4)
            make_pdf(second, 2)
            self.assertEqual(pdf_module.count_pages(source), 4)
            extracted = directory / "extract.pdf"
            self.assertEqual(pdf_module.extract(source, extracted, "4,2"), 2)
            self.assertEqual(len(PdfReader(str(extracted)).pages), 2)
            rotated = directory / "rotate.pdf"
            self.assertEqual(pdf_module.rotate(source, rotated, 90), 4)
            self.assertEqual(PdfReader(str(rotated)).pages[0].get("/Rotate"), 90)
            removed = directory / "removed.pdf"
            self.assertEqual(pdf_module.remove(source, removed, "2-3"), 2)
            self.assertEqual(pdf_module.count_pages(removed), 2)
            merged = directory / "merged.pdf"
            self.assertEqual(pdf_module.merge([source, second], merged), 6)
            self.assertEqual(pdf_module.count_pages(merged), 6)
            # Input PDF remains intact even after multiple operations.
            self.assertEqual(pdf_module.count_pages(source), 4)
            with self.assertRaises(ValueError):
                pdf_module.extract(source, directory / "invalid.pdf", "5")
            with self.assertRaises(ValueError):
                pdf_module.remove(source, directory / "all.pdf", "1-4")
            with self.assertRaises(ValueError):
                pdf_module.rotate(source, directory / "invalid-rotation.pdf", 45)

    def test_api_info_dispatch_preserves_shape(self):
        source = Path("/private/input.pdf")
        with patch.object(server, "pdf_module") as module:
            module.count_pages.return_value = 8
            self.assertEqual(
                server._info_action(source, "pdf:info"),
                {"info": {"pages": 8}},
            )
            module.count_pages.assert_called_once_with(source)
            module.extract.assert_not_called()
            self.assertIsNone(server._info_action(source, "invalid:action"))

    def test_api_pdf_transform_preserves_naming_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "source.pdf"
            cases = (
                ("pdf:rotate", "", "rotated.pdf", "rotate", (source, directory / "rotated.pdf", 90)),
                ("pdf:first", "", "result.pdf", "extract", (source, directory / "result.pdf", "1")),
                ("pdf:extract", "2,4", "result.pdf", "extract", (source, directory / "result.pdf", "2,4")),
                ("pdf:remove", "1", "result.pdf", "remove", (source, directory / "result.pdf", "1")),
            )
            for action, pages, filename, method, args in cases:
                with self.subTest(action=action):
                    with patch.object(server, "pdf_module") as module:
                        target = server._transform(source, directory, action, pages)
                        self.assertEqual(target, directory / filename)
                        getattr(module, method).assert_called_once_with(*args)
                        for other in ("count_pages", "extract", "rotate", "merge", "remove"):
                            if other != method:
                                getattr(module, other).assert_not_called()

    def test_api_pdf_failure_is_not_silenced(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "source.pdf"
            with patch.object(server, "pdf_module") as module:
                module.remove.side_effect = ValueError("cannot remove all")
                with self.assertRaisesRegex(ValueError, "cannot remove all"):
                    server._transform(source, directory, "pdf:remove", "1-3")

    def test_image_dispatch_stays_independent_from_pdf_module(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / "source.png"
            with (
                patch.object(server, "pdf_module") as pdf,
                patch.object(server, "image_module") as image_module,
            ):
                target = server._transform(source, directory, "img:PNG", "")
                self.assertEqual(target, directory / "converted.png")
                image_module.convert.assert_called_once_with(source, target, "PNG")
                pdf.count_pages.assert_not_called()
                pdf.extract.assert_not_called()
                pdf.rotate.assert_not_called()
                pdf.remove.assert_not_called()
                pdf.merge.assert_not_called()

    def test_api_pdf_action_catalog_is_unchanged(self):
        from api.conversion_catalog import SUPPORTED
        self.assertEqual(SUPPORTED["pdf"], {
            "pdf:rotate", "pdf:first", "pdf:extract", "pdf:remove", "pdf:info",
        })


if __name__ == "__main__":
    unittest.main()
