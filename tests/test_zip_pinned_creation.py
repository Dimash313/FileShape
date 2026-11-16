"""Regression tests for ZIP writer input descriptor pinning.

Fixtures are short synthetic plain text/binary strings without media.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from services.archive_tools import make_zip, inspect_zip, unpack_zip


class ZipPinnedCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = self.root / "first.txt"
        self.second = self.root / "second.txt"
        self.first.write_bytes(b"approved-contents")
        self.second.write_bytes(b"second approved file")
        self.output = self.root / "output.zip"

    def assert_no_staging(self):
        self.assertFalse(list(self.root.glob(".fileshape_zip_*.zip")))

    def test_regular_path_replacement_after_open_keeps_original_contents(self):
        replacement = self.root / "replacement.txt"
        replacement.write_bytes(b"entirely different content after validation")
        actual = zipfile.ZipFile.open
        swapped = False

        def replace_during_first_entry(archive, name, mode="r", *args, **kwargs):
            nonlocal swapped
            if mode == "w" and not swapped:
                swapped = True
                os.replace(replacement, self.first)
            return actual(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", autospec=True,
                          side_effect=replace_during_first_entry):
            self.assertEqual(make_zip(
                [(self.first, "first.txt"), (self.second, "second.txt")],
                self.output,
            ), 2)
        self.assertTrue(swapped)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("first.txt"), b"approved-contents")
            self.assertEqual(archive.read("second.txt"), b"second approved file")
        self.assertEqual(self.first.read_bytes(), b"entirely different content after validation")
        self.assert_no_staging()

    def test_high_ratio_fallback_reuses_original_inode_after_path_swap(self):
        original = b"R" * 400_000
        self.first.write_bytes(original)
        replacement = self.root / "replacement.txt"
        replacement.write_bytes(b"replacement must not be included")
        actual = zipfile.ZipFile.open
        count = 0

        def substitute_before_rebuild(archive, name, mode="r", *args, **kwargs):
            nonlocal count
            if mode == "w" and getattr(name, "filename", "") == "first.txt":
                count += 1
                if count == 2:
                    os.replace(replacement, self.first)
            return actual(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", autospec=True,
                          side_effect=substitute_before_rebuild):
            self.assertEqual(make_zip(
                [(self.first, "first.txt"), (self.second, "second.txt")],
                self.output,
            ), 2)
        self.assertEqual(count, 2)
        self.assertEqual(inspect_zip(self.output)["files"], 2)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.getinfo("first.txt").compress_type,
                             zipfile.ZIP_STORED)
            self.assertEqual(archive.read("first.txt"), original)
        self.assert_no_staging()

    def test_symbolic_link_rejected_without_creating_output(self):
        link = self.root / "alias.txt"
        try:
            link.symlink_to(self.first)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink not supported: {error}")
        with self.assertRaisesRegex(ValueError, "недоступен"):
            make_zip([(link, "alias.txt"), (self.second, "second.txt")], self.output)
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_fifo_rejected_without_open_block(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "недоступен"):
            make_zip([(self.first, "first.txt"), (fifo, "fifo")], self.output)
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_mutated_inode_size_during_write_fails_and_preserves_old_target(self):
        self.output.write_bytes(b"old output must remain untouched")
        actual = zipfile.ZipFile.open
        grown = False

        def grow_after_preflight(archive, name, mode="r", *args, **kwargs):
            nonlocal grown
            if mode == "w" and not grown:
                grown = True
                with self.first.open("ab") as writer:
                    writer.write(b"additional unapproved bytes")
            return actual(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", autospec=True,
                          side_effect=grow_after_preflight):
            with self.assertRaisesRegex(ValueError, "изменился"):
                make_zip(
                    [(self.first, "first.txt"), (self.second, "second.txt")],
                    self.output,
                )
        self.assertTrue(grown)
        self.assertEqual(self.output.read_bytes(), b"old output must remain untouched")
        self.assert_no_staging()

    def test_same_length_in_place_rewrite_is_rejected(self):
        """An unchanged length does not mean an approved source is unchanged."""
        previous = b"original target stays available"
        self.output.write_bytes(previous)
        original_size = self.first.stat().st_size
        replacement = b"Z" * original_size
        original = zipfile.ZipFile.open
        overwritten = False

        def rewrite_source_during_write(archive, name, mode="r", *args, **kwargs):
            nonlocal overwritten
            if mode == "w" and not overwritten:
                overwritten = True
                before = self.first.stat()
                self.first.write_bytes(replacement)
                # Exercise the metadata guard independent of filesystem clock
                # resolution: the contents change but the byte count does not.
                os.utime(self.first, ns=(
                    before.st_atime_ns, before.st_mtime_ns + 2_000_000_000,
                ))
                self.assertEqual(self.first.stat().st_size, original_size)
            return original(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", autospec=True,
                          side_effect=rewrite_source_during_write):
            with self.assertRaisesRegex(ValueError, "изменился"):
                make_zip(
                    [(self.first, "first.txt"), (self.second, "second.txt")],
                    self.output,
                )
        self.assertTrue(overwritten)
        self.assertEqual(self.first.read_bytes(), replacement)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assert_no_staging()

    def test_same_length_mutation_before_stored_rebuild_is_rejected(self):
        """A high-ratio fallback must not publish changed bytes of same size."""
        self.first.write_bytes(b"R" * 400_000)
        previous = b"existing archive must stay intact"
        self.output.write_bytes(previous)
        original = zipfile.ZipFile.open
        count = 0

        def overwrite_on_rebuild(archive, name, mode="r", *args, **kwargs):
            nonlocal count
            if mode == "w" and getattr(name, "filename", "") == "first.txt":
                count += 1
                if count == 2:
                    before = self.first.stat()
                    with self.first.open("r+b") as writer:
                        writer.write(b"S" * 16)
                    os.utime(self.first, ns=(
                        before.st_atime_ns, before.st_mtime_ns + 2_000_000_000,
                    ))
                    self.assertEqual(self.first.stat().st_size, 400_000)
            return original(archive, name, mode, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "open", autospec=True,
                          side_effect=overwrite_on_rebuild):
            with self.assertRaisesRegex(ValueError, "изменился"):
                make_zip(
                    [(self.first, "first.txt"), (self.second, "second.txt")],
                    self.output,
                )
        self.assertEqual(count, 2)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assert_no_staging()

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "Linux descriptor test")
    def test_rejected_second_source_does_not_leak_first_source_descriptor(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        before = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(10):
            with self.assertRaises(ValueError):
                make_zip([(self.first, "first.txt"), (fifo, "bad")], self.output)
        after = len(list(Path("/proc/self/fd").iterdir()))
        self.assertEqual(before, after)
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_ordinary_zip_outputs_keep_reader_contract(self):
        self.assertEqual(make_zip(
            [(self.first, "dir/file.txt"), (self.second, "dir/file.txt")],
            self.output,
        ), 2)
        summary = inspect_zip(self.output)
        self.assertEqual(summary["names"], ["file.txt", "file_2.txt"])
        extracted = unpack_zip(self.output, self.root)
        self.assertEqual([path.read_bytes() for path, _ in extracted],
                         [b"approved-contents", b"second approved file"])
        self.assert_no_staging()


if __name__ == "__main__":
    unittest.main()
