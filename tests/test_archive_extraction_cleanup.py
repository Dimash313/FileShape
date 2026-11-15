"""Adversarial ZIP extraction regressions: stage first, no overwrite, rollback."""
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from services import archive_tools


class ZipExtractionCleanupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "output"
        self.output.mkdir()

    def zip_from(self, members, *, compression=zipfile.ZIP_STORED):
        path = self.root / "input.zip"
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, payload in members:
                archive.writestr(name, payload)
        return path

    def assert_clean(self):
        self.assertEqual(list(self.output.glob(".fileshape_extract_*")), [])

    def test_success_keeps_flat_indexed_names_and_order(self):
        source = self.zip_from([
            ("first/duplicate.txt", b"first"),
            ("second/duplicate.txt", b"second"),
        ])
        paths = archive_tools.unpack_zip(source, self.output)
        self.assertEqual(
            [name for _, name in paths], ["01_duplicate.txt", "02_duplicate.txt"]
        )
        self.assertEqual([path.read_bytes() for path, _ in paths], [b"first", b"second"])
        self.assertTrue(all(path.parent == self.output for path, _ in paths))
        self.assert_clean()

    def test_real_bad_crc_in_second_file_leaves_no_partial_results(self):
        marker = b"second-payload-for-crc-test"
        source = self.zip_from([("first.txt", b"first"), ("second.txt", marker)])
        data = source.read_bytes()
        self.assertEqual(data.count(marker), 1)
        source.write_bytes(data.replace(marker, b"X" + marker[1:], 1))
        # Central directory lengths and declared budgets remain valid.
        self.assertEqual(archive_tools.inspect_zip(source)["files"], 2)
        with self.assertRaisesRegex(ValueError, "ZIP"):
            archive_tools.unpack_zip(source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assert_clean()

    def test_preexisting_regular_destination_survives_collision(self):
        source = self.zip_from([("first.txt", b"first"), ("second.txt", b"second")])
        existing = self.output / "02_second.txt"
        existing.write_bytes(b"existing user data")
        with self.assertRaises(FileExistsError):
            archive_tools.unpack_zip(source, self.output)
        self.assertEqual(existing.read_bytes(), b"existing user data")
        self.assertFalse((self.output / "01_first.txt").exists())
        self.assert_clean()

    def test_preexisting_symlink_is_never_followed_or_replaced(self):
        source = self.zip_from([("item.txt", b"new data")])
        outside = self.root / "important.txt"
        outside.write_bytes(b"keep me")
        link = self.output / "01_item.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"filesystem does not support symlinks: {error}")
        with self.assertRaises(FileExistsError):
            archive_tools.unpack_zip(source, self.output)
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_bytes(), b"keep me")
        self.assert_clean()

    def test_failure_during_second_publish_rolls_back_first_link(self):
        source = self.zip_from([("a.txt", b"A"), ("b.txt", b"B")])
        real_link = os.link
        calls = 0

        def fail_second(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated publish failure")
            return real_link(src, dst)

        with patch.object(archive_tools.os, "link", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "publish failure"):
                archive_tools.unpack_zip(source, self.output)
        self.assertEqual(calls, 2)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assert_clean()

    def test_actual_bytes_above_declared_member_are_rejected_and_cleaned(self):
        source = self.zip_from([("small.txt", b"x")])
        # Fake an archive decoder that emits more bytes than its metadata;
        # enforcement must occur before writing the offending chunk.
        with patch.object(archive_tools, "MAX_MEMBER_BYTES", 4):
            with patch.object(zipfile.ZipFile, "open", return_value=io.BytesIO(b"12345")):
                with self.assertRaisesRegex(ValueError, "лимит"):
                    archive_tools.unpack_zip(source, self.output)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assert_clean()

    def test_revalidates_swapped_archive_after_inspection(self):
        original = self.zip_from([("ok.txt", b"safe")])
        replacement = self.root / "replacement.zip"
        with zipfile.ZipFile(replacement, "w") as writer:
            writer.writestr("../escape.txt", b"unsafe")
        original_inspect = archive_tools.inspect_zip

        def swap_after_inspect(path):
            result = original_inspect(path)
            os.replace(replacement, path)
            return result

        with patch.object(archive_tools, "inspect_zip", side_effect=swap_after_inspect):
            with self.assertRaises(ValueError):
                archive_tools.unpack_zip(original, self.output)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assert_clean()

    def test_existing_zip_bomb_and_count_checks_stay_strict(self):
        bomb = self.zip_from(
            [("bomb.txt", b"A" * 400_000)], compression=zipfile.ZIP_DEFLATED
        )
        with self.assertRaisesRegex(ValueError, "сжатие"):
            archive_tools.unpack_zip(bomb, self.output)
        self.assert_clean()
        many = self.zip_from([(f"{n}.txt", b"x") for n in range(11)])
        with self.assertRaisesRegex(ValueError, "1–10"):
            archive_tools.unpack_zip(many, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_symlink_as_output_directory_is_rejected(self):
        source = self.zip_from([("a.txt", b"a")])
        aliased = self.root / "alias"
        try:
            aliased.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"filesystem does not support symlinks: {error}")
        with self.assertRaisesRegex(ValueError, "Каталог"):
            archive_tools.unpack_zip(source, aliased)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
