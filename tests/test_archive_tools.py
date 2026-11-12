"""ZIP regression tests: path traversal, bombs and round-trip archives."""
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from services.archive_tools import inspect_zip, make_zip, unpack_zip


class ZipToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_round_trip_and_duplicate_names(self):
        left = self.folder / "left.txt"
        right = self.folder / "right.txt"
        left.write_text("hello", encoding="utf-8")
        right.write_text("world", encoding="utf-8")
        output = self.folder / "output.zip"
        self.assertEqual(make_zip([(left, "folder/a.txt"), (right, "folder/a.txt")], output), 2)
        info = inspect_zip(output)
        self.assertEqual(info["files"], 2)
        self.assertEqual(info["names"], ["a.txt", "a_2.txt"])
        results = unpack_zip(output, self.folder)
        self.assertEqual([path.read_text() for path, _ in results], ["hello", "world"])
        self.assertTrue(all(path.parent == self.folder for path, _ in results))

    def test_nested_archive_names_are_flattened(self):
        output = self.folder / "nested.zip"
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("docs/example.txt", "hello")
        results = unpack_zip(output, self.folder)
        self.assertEqual(results[0][1], "01_example.txt")

    def test_reject_traversal_and_absolute_paths(self):
        for unsafe in ("../escape.txt", "/root/file.txt", "C:/system.txt", "dir\\escape.txt"):
            with self.subTest(filename=unsafe):
                output = self.folder / "unsafe.zip"
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr(unsafe, "bad")
                with self.assertRaises(ValueError):
                    inspect_zip(output)

    def test_reject_symlinks(self):
        output = self.folder / "symlink.zip"
        info = zipfile.ZipInfo("shortcut")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(info, "target")
        with self.assertRaises(ValueError):
            inspect_zip(output)

    def test_reject_high_compression_ratio(self):
        output = self.folder / "bomb.zip"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("many.txt", "A" * 400_000)
        with self.assertRaises(ValueError):
            inspect_zip(output)

    def test_unpack_has_file_count_limit(self):
        output = self.folder / "many.zip"
        with zipfile.ZipFile(output, "w") as archive:
            for index in range(11):
                archive.writestr(f"{index}.txt", "x")
        self.assertEqual(inspect_zip(output)["files"], 11)
        with self.assertRaises(ValueError):
            unpack_zip(output, self.folder)


if __name__ == "__main__":
    unittest.main()
