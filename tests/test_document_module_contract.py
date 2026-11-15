"""DOCX/TXT domain contract, API compatibility, and real-file regressions.

All fixtures are temporary and generated locally. This module does not
claim DOCX visual-layout fidelity; the existing feature is text export.
"""
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from docx import Document

from api import server
from api.conversion_catalog import SUPPORTED
from services import document_tools
from services.document_module import (
    DocumentModulePort, ExistingDocumentModule, document_module,
)


class DocumentPortTests(unittest.TestCase):
    def test_adapter_implements_document_protocol(self):
        self.assertIsInstance(document_module, DocumentModulePort)

    def test_existing_implementation_delegation_and_returns(self):
        adapter = ExistingDocumentModule()
        source = Path("/private/source.docx")
        target = Path("/private/result.txt")
        word_info = {"paragraphs": 2, "tables": 1, "characters": 33}
        text_info = {"lines": 4, "characters": 12}
        with patch.object(document_tools, "read_docx_text",
                          return_value=("content", word_info)) as read:
            self.assertIs(adapter.inspect_docx(source), word_info)
            read.assert_called_once_with(source)
        with patch.object(document_tools, "txt_info",
                          return_value=text_info) as inspect:
            self.assertIs(adapter.inspect_text(source), text_info)
            inspect.assert_called_once_with(source)
        with patch.object(document_tools, "docx_to_txt",
                          return_value=word_info) as convert:
            self.assertIs(adapter.to_text(source, target), word_info)
            convert.assert_called_once_with(source, target)
        with patch.object(document_tools, "txt_to_docx",
                          return_value=text_info) as convert:
            self.assertIs(adapter.to_docx(source, target), text_info)
            convert.assert_called_once_with(source, target)

    def test_real_utf8_text_docx_text_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            text = root / "source.txt"
            docx = root / "converted.docx"
            recovered = root / "back.txt"
            text.write_text("Привет\nWorld", encoding="utf-8")
            info = document_module.inspect_text(text)
            self.assertEqual(info["lines"], 2)
            converted = document_module.to_docx(text, docx)
            self.assertEqual(converted["lines"], 2)
            self.assertEqual(len(Document(str(docx)).paragraphs), 2)
            inspected = document_module.inspect_docx(docx)
            self.assertEqual(inspected["paragraphs"], 2)
            written = document_module.to_text(docx, recovered)
            self.assertEqual(written["paragraphs"], 2)
            self.assertEqual(recovered.read_text(encoding="utf-8"), "Привет\nWorld")

    def test_docx_table_contents_are_preserved_as_plain_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "table.docx"
            output = root / "table.txt"
            doc = Document()
            doc.add_paragraph("Heading")
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "A"
            table.cell(0, 1).text = "B"
            doc.save(str(source))
            info = document_module.to_text(source, output)
            self.assertEqual(info["tables"], 1)
            self.assertIn("A\tB", output.read_text(encoding="utf-8"))

    def test_invalid_or_oversized_documents_do_not_produce_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_docx = root / "fake.docx"
            out = root / "out.txt"
            with zipfile.ZipFile(fake_docx, "w") as archive:
                archive.writestr("not-a-docx.txt", "hello")
            with self.assertRaisesRegex(ValueError, "не документ DOCX"):
                document_module.to_text(fake_docx, out)
            self.assertFalse(out.exists())
            binary_txt = root / "binary.txt"
            binary_txt.write_bytes(b"one\x00two")
            with self.assertRaises(ValueError):
                document_module.to_docx(binary_txt, root / "out.docx")
            too_large = root / "large.txt"
            with too_large.open("wb") as file:
                file.truncate(document_tools.MAX_TEXT_BYTES + 1)
            with self.assertRaises(ValueError):
                document_module.inspect_text(too_large)

    def test_api_info_shape_and_dispatch_are_unchanged(self):
        source = Path("/private/source.docx")
        word_info = {"paragraphs": 2, "tables": 1, "characters": 33}
        text_info = {"lines": 4, "characters": 12}
        with patch.object(server, "document_module") as module:
            module.inspect_docx.return_value = word_info
            module.inspect_text.return_value = text_info
            self.assertEqual(server._info_action(source, "docx:info"),
                             {"info": word_info})
            self.assertEqual(server._info_action(source, "txt:info"),
                             {"info": text_info})
            module.inspect_docx.assert_called_once_with(source)
            module.inspect_text.assert_called_once_with(source)
            module.to_docx.assert_not_called()
            module.to_text.assert_not_called()

    def test_api_conversion_names_and_errors_are_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "original.docx"
            with patch.object(server, "document_module") as module:
                result = server._transform(source, root, "docx:txt", "")
                self.assertEqual(result, root / "converted.txt")
                module.to_text.assert_called_once_with(
                    source, root / "converted.txt",
                )
                module.to_docx.assert_not_called()
            with patch.object(server, "document_module") as module:
                source = root / "original.txt"
                result = server._transform(source, root, "txt:docx", "")
                self.assertEqual(result, root / "converted.docx")
                module.to_docx.assert_called_once_with(
                    source, root / "converted.docx",
                )
                module.to_text.assert_not_called()
                module.to_docx.side_effect = ValueError("invalid UTF-8")
                with self.assertRaisesRegex(ValueError, "invalid UTF-8"):
                    server._transform(source, root, "txt:docx", "")

    def test_document_dispatch_does_not_call_image_audio_or_pdf_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(server, "document_module") as documents,
                patch.object(server, "image_module") as images,
                patch.object(server, "audio_module") as audio,
                patch.object(server, "pdf_module") as pdf,
            ):
                server._transform(root / "original.docx", root, "docx:txt", "")
                documents.to_text.assert_called_once()
                for other in (images, audio, pdf):
                    other.convert.assert_not_called() if hasattr(other, "convert") else None
                    other.rotate.assert_not_called() if hasattr(other, "rotate") else None

    def test_public_document_action_catalog_unchanged(self):
        self.assertEqual(SUPPORTED["docx"], {"docx:info", "docx:txt"})
        self.assertEqual(SUPPORTED["txt"], {"txt:info", "txt:docx"})


if __name__ == "__main__":
    unittest.main()
