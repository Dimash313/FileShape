"""Atomic generated PDF output: no truncation on writer or publication failures."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from services.pdf_module import pdf_module


def make_pdf(path: Path, count: int) -> None:
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)


class AtomicPdfOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.first = self.root / "first.pdf"
        self.second = self.root / "second.pdf"
        self.target = self.root / "result.pdf"
        make_pdf(self.first, 3)
        make_pdf(self.second, 1)

    def operations(self):
        return (
            ("extract", lambda: pdf_module.extract(self.first, self.target, "1-2"), 2),
            ("rotate", lambda: pdf_module.rotate(self.first, self.target, 90), 3),
            ("merge", lambda: pdf_module.merge([self.first, self.second], self.target), 4),
            ("remove", lambda: pdf_module.remove(self.first, self.target, "2"), 2),
        )

    def assert_no_staged_output(self):
        self.assertEqual(
            list(self.root.glob(f".{self.target.name}.*.tmp")),
            [],
            "Failed PDF operation left a temporary file behind",
        )

    def test_partial_write_failure_preserves_previous_output_for_all_operations(self):
        previous = b"PREVIOUS-OUTPUT-MUST-REMAIN"

        def fail_after_partial_write(_writer, stream):
            stream.write(b"%PDF-1.7\nPARTIAL")
            raise OSError("injected writer failure")

        for name, operation, _pages in self.operations():
            with self.subTest(operation=name):
                self.target.write_bytes(previous)
                with patch.object(PdfWriter, "write", fail_after_partial_write):
                    with self.assertRaisesRegex(OSError, "injected writer failure"):
                        operation()
                self.assertEqual(self.target.read_bytes(), previous)
                self.assert_no_staged_output()

    def test_failure_leaves_no_output_if_none_existed(self):
        self.assertFalse(self.target.exists())

        def fail_after_partial_write(_writer, stream):
            stream.write(b"PARTIAL")
            raise OSError("injected writer failure")

        with patch.object(PdfWriter, "write", fail_after_partial_write):
            with self.assertRaisesRegex(OSError, "injected writer failure"):
                pdf_module.rotate(self.first, self.target, 90)
        self.assertFalse(self.target.exists())
        self.assert_no_staged_output()

    def test_replace_failure_preserves_previous_output_and_cleans_temp(self):
        previous = b"OLD-RESULT"
        self.target.write_bytes(previous)
        with patch("services.pdf_tools.os.replace", side_effect=OSError("publish denied")):
            with self.assertRaisesRegex(OSError, "publish denied"):
                pdf_module.extract(self.first, self.target, "1")
        self.assertEqual(self.target.read_bytes(), previous)
        self.assert_no_staged_output()

    def test_successful_operations_publish_valid_pdfs(self):
        for name, operation, expected_pages in self.operations():
            with self.subTest(operation=name):
                self.target.write_bytes(b"OLD-RESULT")
                self.assertEqual(operation(), expected_pages)
                with self.target.open("rb") as stream:
                    reader = PdfReader(stream)
                    self.assertEqual(len(reader.pages), expected_pages)
                self.assert_no_staged_output()

    def test_existing_output_symlink_does_not_modify_its_referent(self):
        external = self.root / "protected.txt"
        external.write_bytes(b"KEEP-ME")
        self.target.symlink_to(external)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(pdf_module.rotate(self.first, self.target, 90), 3)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(external.read_bytes(), b"KEEP-ME")
        self.assertEqual(pdf_module.count_pages(self.target), 3)
        self.assert_no_staged_output()

    def test_source_and_target_can_share_path_without_truncation(self):
        self.assertEqual(pdf_module.rotate(self.first, self.first, 180), 3)
        self.assertEqual(pdf_module.count_pages(self.first), 3)
        self.assertEqual(list(self.root.glob(".first.pdf.*.tmp")), [])

    def test_temporary_writer_file_uses_private_permissions(self):
        def inspect_writer(_writer, stream):
            self.assertEqual(stat.S_IMODE(os.fstat(stream.fileno()).st_mode), 0o600)
            stream.write(b"X")
            raise OSError("stop after inspecting")

        with patch.object(PdfWriter, "write", inspect_writer):
            with self.assertRaisesRegex(OSError, "stop after inspecting"):
                pdf_module.extract(self.first, self.target, "1")
        self.assert_no_staged_output()


if __name__ == "__main__":
    unittest.main()
