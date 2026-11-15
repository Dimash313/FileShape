"""Hard UTF-8 TXT byte limit on the bytes actually read from disk."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document

from services import document_tools
from services.document_module import document_module


class GrowingOnOpenPath(type(Path())):
    """Simulate a file growing after a hypothetical earlier stat() result."""

    def open(self, mode="r", *args, **kwargs):
        if mode == "rb":
            with super().open("wb") as sink:
                sink.write(("界" * 700_000).encode("utf-8"))
        return super().open(mode, *args, **kwargs)


class BoundedTxtReadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "input.txt"
        self.target = self.root / "converted.docx"

    def test_actual_byte_limit_exactly_two_mib_allows_unicode(self):
        # 699050 three-byte characters + 2 ASCII bytes = exactly 2 MiB,
        # and the resulting 699052 characters stay below the char limit.
        data = ("界" * 699_050 + "AB").encode("utf-8")
        self.assertEqual(len(data), document_tools.MAX_TEXT_BYTES)
        self.source.write_bytes(data)
        content = document_tools.read_plain_text(self.source)
        self.assertEqual(len(content), 699_052)
        self.assertTrue(content.endswith("AB"))

    def test_actual_byte_limit_one_byte_over_rejected(self):
        data = ("界" * 699_051).encode("utf-8")
        self.assertEqual(len(data), document_tools.MAX_TEXT_BYTES + 1)
        self.source.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "TXT превышает лимит 2 МБ"):
            document_tools.read_plain_text(self.source)

    def test_growing_file_cannot_bypass_byte_limit(self):
        growing = GrowingOnOpenPath(self.root / "growing.txt")
        growing.write_bytes(b"old")
        # Old stat()->unbounded read_bytes() accepted the 700000 chars
        # despite the 2.1 MB byte length. A bounded read must reject it.
        with self.assertRaisesRegex(ValueError, "TXT превышает лимит 2 МБ"):
            document_tools.read_plain_text(growing)
        self.assertEqual(growing.stat().st_size, 2_100_000)

    def test_read_does_not_use_stat_or_unbounded_read_bytes(self):
        self.source.write_text("Текст ✓", encoding="utf-8")
        with patch.object(Path, "stat", side_effect=AssertionError("stale stat used")):
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("unbounded read_bytes used")
            ):
                self.assertEqual(document_tools.read_plain_text(self.source), "Текст ✓")

    def test_rejected_oversized_input_does_not_create_docx(self):
        self.source.write_bytes(("界" * 699_051).encode("utf-8"))
        self.assertFalse(self.target.exists())
        with self.assertRaisesRegex(ValueError, "TXT превышает лимит 2 МБ"):
            document_module.to_docx(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_utf8_bom_and_newline_preserved_in_generated_docx(self):
        self.source.write_bytes(b"\xef\xbb\xbf" + "Привет\n第二行".encode("utf-8"))
        self.assertEqual(
            document_tools.read_plain_text(self.source), "Привет\n第二行"
        )
        info = document_module.to_docx(self.source, self.target)
        self.assertEqual(info["lines"], 2)
        self.assertEqual(
            [p.text for p in Document(str(self.target)).paragraphs],
            ["Привет", "第二行"],
        )

    def test_invalid_utf8_and_binary_nul_keep_existing_errors(self):
        for payload, message in (
            (b"\xff\xfe\xfb", "Нужен TXT в кодировке UTF-8"),
            (b"abc\x00def", "Похоже, это не текстовый файл"),
        ):
            with self.subTest(payload=payload):
                self.source.write_bytes(payload)
                with self.assertRaisesRegex(ValueError, message):
                    document_tools.read_plain_text(self.source)

    def test_character_and_line_limits_still_apply(self):
        for payload in (
            b"A" * (document_tools.MAX_TEXT_CHARS + 1),
            b"x\n" * (document_tools.MAX_TEXT_LINES + 1),
        ):
            with self.subTest(length=len(payload)):
                self.source.write_bytes(payload)
                with self.assertRaisesRegex(ValueError, "Слишком большой текст"):
                    document_tools.read_plain_text(self.source)


if __name__ == "__main__":
    unittest.main()
