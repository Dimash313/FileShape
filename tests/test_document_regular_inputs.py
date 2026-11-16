"""DOCX/TXT inputs must be regular files; symlinks and FIFOs are not uploads."""
import io
import os
from pathlib import Path
import tempfile
import unittest

from docx import Document

from services import document_tools
from services.document_module import document_module


class RegularDocumentInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.docx = self.root / "genuine.docx"
        self.txt = self.root / "genuine.txt"
        self.docx_output = self.root / "result.txt"
        self.txt_output = self.root / "result.docx"

        word = Document()
        word.add_paragraph("Обычный документ")
        word.save(self.docx)
        self.txt.write_text("Обычный текст ✓", encoding="utf-8")

    def test_normal_regular_inputs_preserve_text_and_word_conversion(self):
        self.assertEqual(document_tools.read_plain_text(self.txt), "Обычный текст ✓")
        document_tools.validate_docx(self.docx)
        result = document_module.to_text(self.docx, self.docx_output)
        self.assertEqual(result["paragraphs"], 1)
        self.assertEqual(
            self.docx_output.read_text(encoding="utf-8"), "Обычный документ"
        )
        info = document_module.to_docx(self.txt, self.txt_output)
        self.assertEqual(info["lines"], 1)
        self.assertEqual(
            Document(str(self.txt_output)).paragraphs[0].text, "Обычный текст ✓"
        )

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW unavailable")
    def test_docx_symlink_input_rejected_by_validator_and_exports(self):
        link = self.root / "alias.docx"
        link.symlink_to(self.docx)
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_tools.validate_docx(link)
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_module.inspect_docx(link)
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_module.to_text(link, self.docx_output)
        self.assertFalse(self.docx_output.exists())
        self.assertEqual(Document(str(self.docx)).paragraphs[0].text,
                         "Обычный документ")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW unavailable")
    def test_txt_symlink_input_rejected_by_inspection_and_conversion(self):
        link = self.root / "alias.txt"
        link.symlink_to(self.txt)
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_module.inspect_text(link)
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_module.to_docx(link, self.txt_output)
        self.assertFalse(self.txt_output.exists())
        self.assertEqual(self.txt.read_text(encoding="utf-8"), "Обычный текст ✓")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW unavailable")
    def test_dangling_symlink_is_not_treated_as_missing_source(self):
        link = self.root / "dangling.txt"
        link.symlink_to(self.root / "missing.txt")
        with self.assertRaisesRegex(ValueError, "Символическая ссылка"):
            document_tools.read_plain_text(link)

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
                         "FIFO nonblocking open unsupported")
    def test_fifo_sources_rejected_without_waiting_for_writers(self):
        fifo = self.root / "upload.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "только обычные файлы"):
            document_tools.read_plain_text(fifo)
        with self.assertRaisesRegex(ValueError, "только обычные файлы"):
            document_tools.validate_docx(fifo)
        self.assertFalse(self.docx_output.exists())
        self.assertFalse(self.txt_output.exists())

    def test_directory_is_not_accepted_as_docx_or_txt_file(self):
        with self.assertRaisesRegex(ValueError, "только обычные файлы"):
            document_tools.validate_docx(self.root)
        with self.assertRaisesRegex(ValueError, "только обычные файлы"):
            document_tools.read_plain_text(self.root)

    def test_missing_source_keeps_native_file_error(self):
        missing = self.root / "not-found.txt"
        with self.assertRaises(FileNotFoundError):
            document_tools.read_plain_text(missing)
        with self.assertRaises(FileNotFoundError):
            document_tools.validate_docx(missing)

    def test_validator_accepts_open_stream_without_closing_caller_stream(self):
        with self.docx.open("rb") as opened:
            document_tools.validate_docx(opened)
            self.assertFalse(opened.closed)
        data = io.BytesIO(self.docx.read_bytes())
        document_tools.validate_docx(data)
        self.assertFalse(data.closed)
        document_tools.validate_docx(str(self.docx))

    def test_malformed_zip_still_returns_stable_error_without_output(self):
        broken = self.root / "bad.docx"
        broken.write_bytes(b"not a ZIP file")
        with self.assertRaisesRegex(ValueError, "Повреждённый DOCX"):
            document_module.to_text(broken, self.docx_output)
        self.assertFalse(self.docx_output.exists())


if __name__ == "__main__":
    unittest.main()
