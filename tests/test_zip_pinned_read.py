"""Regression tests for pinned ZIP inspection and extraction.

Only artificial plain-text ZIP payloads are used; no external media.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from services import archive_tools


class PinnedZipReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.source = self.root / "source.zip"
        with zipfile.ZipFile(self.source, "w") as z:
            z.writestr("docs/first.txt", b"first approved")
            z.writestr("docs/second.txt", b"second approved")

    def assert_no_stage(self):
        self.assertEqual(list(self.output.glob(".fileshape_extract_*")), [])

    def test_inspection_and_extraction_reject_symlink_inputs(self):
        alias = self.root / "source_link.zip"
        try:
            alias.symlink_to(self.source)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.inspect_zip(alias)
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.unpack_zip(alias, self.output)
        self.assertFalse(list(self.output.iterdir()))
        self.assert_no_stage()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_inspection_and_extraction_reject_fifo_without_blocking(self):
        fifo = self.root / "source_fifo.zip"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.inspect_zip(fifo)
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.unpack_zip(fifo, self.output)
        self.assertFalse(list(self.output.iterdir()))
        self.assert_no_stage()

    def test_directory_is_not_accepted_as_zip_source(self):
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.inspect_zip(self.root)
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.unpack_zip(self.root, self.output)
        self.assertFalse(list(self.output.iterdir()))
        self.assert_no_stage()

    def test_zip_creation_rejects_directory_input_before_fdopen(self):
        other = self.root / "other.txt"
        other.write_bytes(b"synthetic file")
        target = self.root / "result.zip"
        with self.assertRaisesRegex(ValueError, "недоступен"):
            archive_tools.make_zip(
                [(self.root, "directory"), (other, "other.txt")],
                target,
            )
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".fileshape_zip_*.zip")), [])

    def test_extract_opens_the_approved_source_only_once(self):
        original_open = archive_tools._open_zip_source
        opened = []

        @contextmanager
        def count_open(path):
            with original_open(path) as (stream, metadata):
                opened.append(stream)
                yield stream, metadata

        with patch.object(archive_tools, "_open_zip_source", side_effect=count_open):
            result = archive_tools.unpack_zip(self.source, self.output)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)
        self.assertEqual([name for _, name in result],
                         ["01_first.txt", "02_second.txt"])
        self.assertEqual([path.read_bytes() for path, _ in result],
                         [b"first approved", b"second approved"])
        self.assert_no_stage()

    def test_inspector_uses_one_regular_source_descriptor(self):
        opened = []
        real_open = archive_tools._open_zip_source

        @contextmanager
        def track_open(path):
            with real_open(path) as (stream, metadata):
                opened.append(stream)
                yield stream, metadata

        with patch.object(archive_tools, "_open_zip_source", side_effect=track_open):
            result = archive_tools.inspect_zip(self.source)
        self.assertEqual(result["files"], 2)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)
        self.assert_no_stage()

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "Linux descriptor listing")
    def test_malformed_archive_does_not_leak_source_descriptors(self):
        corrupt = self.root / "broken.zip"
        corrupt.write_bytes(b"invalid ZIP bytes")
        before = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(12):
            with self.assertRaisesRegex(ValueError, "ZIP"):
                archive_tools.inspect_zip(corrupt)
            with self.assertRaisesRegex(ValueError, "ZIP"):
                archive_tools.unpack_zip(corrupt, self.output)
        after = len(list(Path("/proc/self/fd").iterdir()))
        self.assertEqual(before, after)
        self.assertFalse(list(self.output.iterdir()))
        self.assert_no_stage()


if __name__ == "__main__":
    unittest.main()
