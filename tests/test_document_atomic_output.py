"""Real-file regressions for atomic DOCX/TXT output publication."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.document import Document as DocumentClass

from services import document_tools
from services.document_module import document_module


class AtomicDocumentOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source_docx = self.root / "source.docx"
        self.source_txt = self.root / "source.txt"
        self.to_text = self.root / "result.txt"
        self.to_docx = self.root / "result.docx"
        word = Document()
        word.add_paragraph("Привет, FileShape! ✓")
        word.save(self.source_docx)
        self.source_txt.write_text("Первый\nSecond ✓", encoding="utf-8")

    def assert_no_temporary(self, target):
        self.assertEqual(list(self.root.glob(f".{target.name}.*.tmp")), [])

    def test_successful_exports_keep_unicode_and_counts(self):
        text_info = document_module.to_text(self.source_docx, self.to_text)
        self.assertEqual(
            self.to_text.read_text(encoding="utf-8"), "Привет, FileShape! ✓"
        )
        self.assertEqual(text_info["paragraphs"], 1)

        docx_info = document_module.to_docx(self.source_txt, self.to_docx)
        self.assertEqual(docx_info["lines"], 2)
        self.assertEqual(
            [p.text for p in Document(str(self.to_docx)).paragraphs],
            ["Первый", "Second ✓"],
        )
        self.assert_no_temporary(self.to_text)
        self.assert_no_temporary(self.to_docx)

    def test_partial_txt_write_failure_keeps_existing_output(self):
        previous = b"EXISTING-TEXT"
        self.to_text.write_bytes(previous)
        original = document_tools._write_document_atomically

        def inject_partial_write(target, _writer):
            def fail_writer(stream):
                stream.write(b"PARTIAL")
                raise OSError("text output interrupted")
            return original(target, fail_writer)

        with patch.object(
            document_tools, "_write_document_atomically",
            side_effect=inject_partial_write,
        ):
            with self.assertRaisesRegex(OSError, "text output interrupted"):
                document_module.to_text(self.source_docx, self.to_text)
        self.assertEqual(self.to_text.read_bytes(), previous)
        self.assert_no_temporary(self.to_text)

    def test_partial_docx_write_failure_keeps_existing_output(self):
        previous = b"EXISTING-DOCX"
        self.to_docx.write_bytes(previous)

        def fail_save(_self, stream):
            stream.write(b"PK-PARTIAL")
            raise OSError("Word save interrupted")

        with patch.object(DocumentClass, "save", fail_save):
            with self.assertRaisesRegex(OSError, "Word save interrupted"):
                document_module.to_docx(self.source_txt, self.to_docx)
        self.assertEqual(self.to_docx.read_bytes(), previous)
        self.assert_no_temporary(self.to_docx)

    def test_replace_failure_keeps_both_existing_results(self):
        for action, target in (
            (lambda: document_module.to_text(self.source_docx, self.to_text), self.to_text),
            (lambda: document_module.to_docx(self.source_txt, self.to_docx), self.to_docx),
        ):
            with self.subTest(target=target.name):
                target.write_bytes(b"EXISTING")
                with patch("services.document_tools.os.replace",
                           side_effect=OSError("publication denied")):
                    with self.assertRaisesRegex(OSError, "publication denied"):
                        action()
                self.assertEqual(target.read_bytes(), b"EXISTING")
                self.assert_no_temporary(target)

    def test_write_failure_does_not_create_partial_final_result(self):
        original = document_tools._write_document_atomically

        def inject_error(target, _writer):
            def failing_writer(stream):
                stream.write(b"TRUNCATED")
                raise OSError("interrupted")
            return original(target, failing_writer)

        with patch.object(
            document_tools, "_write_document_atomically",
            side_effect=inject_error,
        ):
            with self.assertRaisesRegex(OSError, "interrupted"):
                document_module.to_text(self.source_docx, self.to_text)
        self.assertFalse(self.to_text.exists())
        self.assert_no_temporary(self.to_text)

    def test_existing_symlink_output_does_not_modify_referent(self):
        protected = self.root / "external.bin"
        protected.write_bytes(b"PRESERVE")
        for action, target in (
            (lambda: document_module.to_text(self.source_docx, self.to_text), self.to_text),
            (lambda: document_module.to_docx(self.source_txt, self.to_docx), self.to_docx),
        ):
            with self.subTest(target=target.name):
                target.symlink_to(protected)
                action()
                self.assertFalse(target.is_symlink())
                self.assertEqual(protected.read_bytes(), b"PRESERVE")
                self.assert_no_temporary(target)

    def test_published_files_have_restricted_permissions(self):
        document_module.to_text(self.source_docx, self.to_text)
        document_module.to_docx(self.source_txt, self.to_docx)
        for target in (self.to_text, self.to_docx):
            with self.subTest(target=target.name):
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_same_path_txt_source_and_docx_output_is_safe(self):
        same = self.root / "same.txt"
        same.write_text("Converted\nSafely", encoding="utf-8")
        info = document_module.to_docx(same, same)
        self.assertEqual(info["lines"], 2)
        self.assertEqual(
            [p.text for p in Document(str(same)).paragraphs],
            ["Converted", "Safely"],
        )
        self.assert_no_temporary(same)


if __name__ == "__main__":
    unittest.main()
