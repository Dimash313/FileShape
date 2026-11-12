"""Malformed real-parser regression cases, not only filename signature checks.

All fixtures are generated in memory. No external files or network needed.
"""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

from docx import Document
from PIL import Image
from pypdf import PdfWriter

from services.archive_tools import inspect_zip
from services.document_tools import read_docx_text
from services.file_tools import pdf_page_count, convert_image
from services.upload_validation import validate_upload


class MalformedFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_truncated_png_rejected_by_real_converter(self):
        data = BytesIO()
        Image.new("RGB", (64, 64), "red").save(data, format="PNG")
        truncated = self.write("broken.png", data.getvalue()[:60])
        with self.assertRaises((ValueError, OSError)):
            convert_image(truncated, self.root / "out.jpg", "JPEG")

    def test_pdf_with_valid_header_but_invalid_structure(self):
        fake = self.write("broken.pdf", b"%PDF-1.7\ninvalid body\n%%EOF")
        validate_upload(fake, ".pdf")
        with self.assertRaises((ValueError, Exception)):
            pdf_page_count(fake)

    def test_valid_pdf_still_reads(self):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        source = self.write("valid.pdf", output.getvalue())
        validate_upload(source, ".pdf")
        self.assertEqual(pdf_page_count(source), 1)

    def test_truncated_zip_rejected(self):
        source = self.write("broken.zip", b"PK\\x03\\x04not-a-central-directory")
        with self.assertRaises(ValueError):
            inspect_zip(source)

    def test_zip_with_parent_directory_rejected(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../escape.txt", b"unsafe")
        source = self.write("unsafe.zip", output.getvalue())
        validate_upload(source, ".zip")
        with self.assertRaises(ValueError):
            inspect_zip(source)

    def test_docx_zip_missing_required_xml_rejected(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("random.txt", b"not a word document")
        source = self.write("fake.docx", output.getvalue())
        validate_upload(source, ".docx")
        with self.assertRaises(ValueError):
            read_docx_text(source)

    def test_valid_docx_still_reads(self):
        document = Document()
        document.add_paragraph("FileShape")
        source = self.root / "valid.docx"
        document.save(source)
        validate_upload(source, ".docx")
        content, _ = read_docx_text(source)
        self.assertIn("FileShape", content)


if __name__ == "__main__":
    unittest.main()
