"""ZIP preflight and python-docx parser must use the same opened input."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document

from services import document_tools
from services.document_module import document_module


class PinnedDocxSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source.docx"
        self.replacement = self.root / "replacement.docx"
        self.output = self.root / "result.txt"
        self.make_docx(self.source, "VALIDATED original")
        self.make_docx(self.replacement, "UNVALIDATED replacement")

    @staticmethod
    def make_docx(path, text):
        doc = Document()
        doc.add_paragraph(text)
        doc.save(path)

    def test_valid_docx_keeps_original_plaintext_output(self):
        result = document_module.to_text(self.source, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "VALIDATED original")
        self.assertEqual(result["paragraphs"], 1)
        self.assertEqual(result["tables"], 0)

    def test_public_validator_accepts_path_and_open_stream(self):
        document_tools.validate_docx(self.source)
        with self.source.open("rb") as stream:
            document_tools.validate_docx(stream)
            self.assertFalse(stream.closed)

    def test_replacing_path_after_preflight_cannot_swap_parsed_document(self):
        real_validate = document_tools.validate_docx

        def replace_after_validation(checked_input):
            real_validate(checked_input)
            os.replace(self.replacement, self.source)

        with patch.object(document_tools, "validate_docx",
                          side_effect=replace_after_validation):
            result = document_module.to_text(self.source, self.output)
        self.assertEqual(result["paragraphs"], 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "VALIDATED original")
        # The pathname really did change. Only the existing descriptor is
        # guaranteed to continue referring to the validated file.
        self.assertEqual(Document(self.source).paragraphs[0].text,
                         "UNVALIDATED replacement")

    def test_renaming_source_after_validation_keeps_parse_available(self):
        old_name = self.root / "renamed-away.docx"
        real_validate = document_tools.validate_docx

        def rename_after_validation(checked_input):
            real_validate(checked_input)
            self.source.rename(old_name)

        with patch.object(document_tools, "validate_docx",
                          side_effect=rename_after_validation):
            result = document_module.to_text(self.source, self.output)
        self.assertEqual(result["paragraphs"], 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "VALIDATED original")
        self.assertFalse(self.source.exists())
        self.assertTrue(old_name.exists())

    def test_corrupt_initial_package_stays_rejected_even_if_path_replaced(self):
        self.source.write_bytes(b"not a ZIP archive")
        real_validate = document_tools.validate_docx

        def replace_even_on_failure(checked_input):
            try:
                real_validate(checked_input)
            finally:
                os.replace(self.replacement, self.source)

        with patch.object(document_tools, "validate_docx",
                          side_effect=replace_even_on_failure):
            with self.assertRaisesRegex(ValueError, "Повреждённый DOCX"):
                document_module.to_text(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(Document(self.source).paragraphs[0].text,
                         "UNVALIDATED replacement")

    def test_parser_failure_closes_pinned_stream_and_normalizes_error(self):
        captured = []

        def fail_parser(stream):
            captured.append(stream)
            raise ValueError("confidential pathname in parser output")

        with patch.object(document_tools, "Document", side_effect=fail_parser):
            with self.assertRaises(ValueError) as raised:
                document_module.inspect_docx(self.source)
        self.assertEqual(str(raised.exception), "Повреждённый DOCX")
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].closed)

    def test_os_error_closes_pinned_stream_without_swallowing_error(self):
        captured = []

        def fail_parser(stream):
            captured.append(stream)
            raise OSError("storage unavailable")

        with patch.object(document_tools, "Document", side_effect=fail_parser):
            with self.assertRaisesRegex(OSError, "storage unavailable"):
                document_module.inspect_docx(self.source)
        self.assertTrue(captured[0].closed)


if __name__ == "__main__":
    unittest.main()
