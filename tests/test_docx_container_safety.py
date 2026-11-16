"""Real generated DOCX package fixtures for ambiguous and unsafe ZIP members."""
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

from docx import Document

from services.document_tools import docx_to_txt, validate_docx


class DocxContainerSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.docx"
        self.target = self.root / "output.txt"
        document = Document()
        document.add_paragraph("Привет, FileShape")
        document.save(self.source)

    def assert_bad_member(self, member, message):
        with zipfile.ZipFile(self.source, "a") as archive:
            archive.writestr(member, "untrusted")
        with self.assertRaisesRegex(ValueError, message):
            docx_to_txt(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_traversal_absolute_and_noncanonical_paths(self):
        for name in ("../outside.xml", "/absolute.xml", "word/../escape.xml",
                     "word/./odd.xml", "word//odd.xml", "word\\bad.xml",
                     "C:/path.xml", "word/control\n.xml"):
            with self.subTest(name=name):
                # Reset the fixture between cases, so only the tested path is bad.
                document = Document()
                document.add_paragraph("Safe")
                document.save(self.source)
                self.assert_bad_member(name, "Недопустимый путь")

    def test_exact_and_casefold_duplicate_member_names(self):
        for name in ("word/document.xml", "WORD/DOCUMENT.XML"):
            with self.subTest(name=name):
                document = Document()
                document.add_paragraph("Safe")
                document.save(self.source)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    self.assert_bad_member(name, "Дублирующийся элемент")

    def test_symlink_member_rejected_before_parsing(self):
        link = zipfile.ZipInfo("word/symlink.xml")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assert_bad_member(link, "Символические ссылки")

    def test_valid_generated_docx_still_converts(self):
        validate_docx(self.source)
        info = docx_to_txt(self.source, self.target)
        self.assertEqual(info["paragraphs"], 1)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "Привет, FileShape")


if __name__ == "__main__":
    unittest.main()
