"""Verify hostile or mislabeled uploads fail before format parsers run."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from services.upload_validation import validate_upload


class UploadValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_valid_png_and_jpeg(self):
        for fmt, ext in (("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")):
            buf = BytesIO()
            Image.new("RGB", (10, 10), "white").save(buf, format=fmt)
            validate_upload(self.write("image" + ext, buf.getvalue()), ext)

    def test_mismatched_image_extension(self):
        buf = BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        with self.assertRaises(ValueError):
            validate_upload(self.write("wrong.jpg", buf.getvalue()), ".jpg")

    def test_reject_fake_pdf_and_audio(self):
        for suffix in (".pdf", ".mp3", ".ogg", ".wav", ".m4a", ".flac"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    validate_upload(self.write("fake" + suffix, b"not-a-real-file"), suffix)

    def test_zip_signature(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("file.txt", "hello")
        validate_upload(self.write("archive.zip", buffer.getvalue()), ".zip")
        with self.assertRaises(ValueError):
            validate_upload(self.write("fake.docx", b"not-a-zip"), ".docx")

    def test_reject_binary_txt(self):
        with self.assertRaises(ValueError):
            validate_upload(self.write("binary.txt", b"hello\x00world"), ".txt")
        validate_upload(self.write("plain.txt", "Привет".encode()), ".txt")


if __name__ == "__main__":
    unittest.main()
