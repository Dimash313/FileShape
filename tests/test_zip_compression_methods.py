"""ZIP method admission regressions using synthetic text-only archives."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from services import archive_tools


def make_unsupported_method_zip(path: Path, *, mixed: bool = False) -> None:
    """Rewrite the compression ID only, in local and central ZIP headers.

    This creates the precise mismatch between metadata admission and decoder
    support without changing any other entry sizes or file payload bytes.
    """
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        if mixed:
            archive.writestr("first.txt", b"first safe text")
        archive.writestr("second.txt", b"second safe text")

    raw = bytearray(path.read_bytes())
    central_signature = b"PK\x01\x02"
    offset = 0
    while True:
        position = raw.find(central_signature, offset)
        if position < 0:
            raise AssertionError("Expected second ZIP central directory entry")
        name_len = struct.unpack_from("<H", raw, position + 28)[0]
        member_name = bytes(raw[position + 46:position + 46 + name_len])
        if member_name == b"second.txt":
            local_offset = struct.unpack_from("<I", raw, position + 42)[0]
            if raw[local_offset:local_offset + 4] != b"PK\x03\x04":
                raise AssertionError("Invalid local ZIP header offset")
            struct.pack_into("<H", raw, position + 10, 99)
            struct.pack_into("<H", raw, local_offset + 8, 99)
            break
        offset = position + 46 + name_len
    path.write_bytes(raw)


class ZipCompressionAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.zip"
        self.target = self.root / "output"
        self.target.mkdir()

    def assert_clean(self):
        self.assertEqual(
            list(self.target.glob(".fileshape_extract_*")), []
        )

    def test_unknown_codec_is_refused_during_inspection(self):
        make_unsupported_method_zip(self.source)
        # A Python ZIP reader can parse this metadata but not decode it.
        with zipfile.ZipFile(self.source) as raw:
            self.assertEqual(raw.infolist()[0].compress_type, 99)
        with self.assertRaisesRegex(ValueError, "метод сжатия"):
            archive_tools.inspect_zip(self.source)
        self.assert_clean()

    def test_unknown_later_member_fails_before_any_decoder_or_publication(self):
        make_unsupported_method_zip(self.source, mixed=True)
        existing = self.target / "01_first.txt"
        existing.write_bytes(b"preserve existing")
        with patch.object(
            zipfile.ZipFile, "open",
            side_effect=AssertionError("unexpected ZIP member decoding"),
        ) as decoder:
            with self.assertRaisesRegex(ValueError, "метод сжатия"):
                archive_tools.unpack_zip(self.source, self.target)
            decoder.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"preserve existing")
        self.assertEqual(list(self.target.iterdir()), [existing])
        self.assert_clean()

    def test_all_supported_zipfile_codecs_remain_extractable(self):
        methods = (
            zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED,
            zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA,
        )
        for method in methods:
            with self.subTest(compression=method):
                source = self.root / f"{method}.zip"
                with zipfile.ZipFile(source, "w", compression=method) as writer:
                    writer.writestr("nested/first.txt", b"abc-123")
                    writer.writestr("nested/second.txt", b"xyz-456")
                summary = archive_tools.inspect_zip(source)
                self.assertEqual(summary["files"], 2)
                with tempfile.TemporaryDirectory(dir=self.root) as name:
                    output = Path(name)
                    actual = archive_tools.unpack_zip(source, output)
                    self.assertEqual(
                        [path.read_bytes() for path, _ in actual],
                        [b"abc-123", b"xyz-456"],
                    )
                    self.assertEqual(
                        [label for _, label in actual],
                        ["01_first.txt", "02_second.txt"],
                    )
                    self.assertEqual(
                        list(output.glob(".fileshape_extract_*")), [],
                    )


if __name__ == "__main__":
    unittest.main()
