"""ZIP archive domain port, API compatibility and real-file safety regressions.

These tests do not widen public API capabilities. ZIP extraction/creation
remain Telegram-only user flows in this phase; the API exposes zip:list.
"""
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from api import server
from api.conversion_catalog import SUPPORTED
from services import archive_tools
from services.archive_module import ArchiveModulePort, ExistingArchiveModule, archive_module


class ArchiveModuleContractTests(unittest.TestCase):
    def test_port_is_implemented(self):
        self.assertIsInstance(archive_module, ArchiveModulePort)

    def test_adapter_delegates_without_changing_args_and_return_shapes(self):
        adapter = ExistingArchiveModule()
        source = Path("/private/old.zip")
        folder = Path("/private/output")
        target = Path("/private/new.zip")
        inputs = [(Path("/private/a.txt"), "a.txt"),
                  (Path("/private/b.txt"), "b.txt")]
        summary = {"files": 2, "bytes": 9, "names": ["a.txt", "b.txt"]}
        entries = [(folder / "01_a.txt", "01_a.txt")]
        with patch.object(archive_tools, "inspect_zip", return_value=summary) as inspect:
            self.assertIs(adapter.inspect(source), summary)
            inspect.assert_called_once_with(source)
        with patch.object(archive_tools, "unpack_zip", return_value=entries) as extract:
            self.assertIs(adapter.extract(source, folder), entries)
            extract.assert_called_once_with(source, folder)
        with patch.object(archive_tools, "make_zip", return_value=2) as create:
            self.assertEqual(adapter.create(inputs, target), 2)
            create.assert_called_once_with(inputs, target)

    def test_real_create_inspect_extract_roundtrip_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            a = folder / "a.txt"
            b = folder / "b.txt"
            a.write_text("first", encoding="utf-8")
            b.write_text("second", encoding="utf-8")
            output = folder / "result.zip"
            inputs = [(a, "dir/report.txt"), (b, "other/report.txt")]
            self.assertEqual(archive_module.create(inputs, output), 2)
            summary = archive_module.inspect(output)
            self.assertEqual(summary["files"], 2)
            self.assertEqual(summary["bytes"], len("firstsecond"))
            self.assertEqual(summary["names"], ["report.txt", "report_2.txt"])
            extracted = archive_module.extract(output, folder)
            self.assertEqual([name for _, name in extracted],
                             ["01_report.txt", "02_report_2.txt"])
            self.assertEqual([p.read_text(encoding="utf-8") for p, _ in extracted],
                             ["first", "second"])
            self.assertTrue(all(p.parent == folder for p, _ in extracted))

    def test_zip_traversal_and_link_entries_are_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            archive_path = folder / "bad.zip"
            for name in ("../outside.txt", "/absolute.txt",
                         "C:/windows.txt", "folder\\windows.txt"):
                with self.subTest(name=name):
                    with zipfile.ZipFile(archive_path, "w") as writer:
                        writer.writestr(name, "evil")
                    with self.assertRaises(ValueError):
                        archive_module.inspect(archive_path)
                    with self.assertRaises(ValueError):
                        archive_module.extract(archive_path, folder)
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive_path, "w") as writer:
                writer.writestr(info, "outside.txt")
            with self.assertRaises(ValueError):
                archive_module.extract(archive_path, folder)
            self.assertFalse((folder.parent / "outside.txt").exists())

    def test_zip_bomb_and_extraction_count_limits_still_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bomb = folder / "bomb.zip"
            with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as writer:
                writer.writestr("huge.txt", "X" * 400_000)
            with self.assertRaises(ValueError):
                archive_module.inspect(bomb)
            with self.assertRaises(ValueError):
                archive_module.extract(bomb, folder)
            many = folder / "many.zip"
            with zipfile.ZipFile(many, "w") as writer:
                for i in range(archive_tools.MAX_EXTRACT_FILES + 1):
                    writer.writestr(f"{i}.txt", "x")
            self.assertEqual(archive_module.inspect(many)["files"],
                             archive_tools.MAX_EXTRACT_FILES + 1)
            with self.assertRaises(ValueError):
                archive_module.extract(many, folder)

    def test_invalid_bundle_sizes_and_corrupt_archive_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            one = folder / "one.txt"
            one.write_text("text", encoding="utf-8")
            target = folder / "output.zip"
            with self.assertRaises(ValueError):
                archive_module.create([(one, "one.txt")], target)
            corrupt = folder / "corrupt.zip"
            corrupt.write_bytes(b"PK fake ZIP bytes")
            with self.assertRaises(ValueError):
                archive_module.inspect(corrupt)

    def test_api_zip_information_response_and_error_propagation(self):
        source = Path("/private/archive.zip")
        summary = {"files": 2, "bytes": 7, "names": ["a.txt", "b.txt"]}
        with patch.object(server, "archive_module") as module:
            module.inspect.return_value = summary
            self.assertEqual(server._info_action(source, "zip:list"),
                             {"info": summary})
            module.inspect.assert_called_once_with(source)
            module.extract.assert_not_called()
            module.create.assert_not_called()
        with patch.object(server, "archive_module") as module:
            module.inspect.side_effect = ValueError("unsafe ZIP")
            with self.assertRaisesRegex(ValueError, "unsafe ZIP"):
                server._info_action(source, "zip:list")

    def test_other_format_dispatch_does_not_call_archive_module(self):
        with patch.object(server, "archive_module") as archive:
            with patch.object(server, "document_module") as document:
                document.inspect_text.return_value = {"lines": 2, "characters": 7}
                self.assertEqual(
                    server._info_action(Path("/private/a.txt"), "txt:info"),
                    {"info": {"lines": 2, "characters": 7}},
                )
                document.inspect_text.assert_called_once()
                self.assertEqual(archive.mock_calls, [])

    def test_api_archive_action_catalog_remains_read_only(self):
        self.assertEqual(SUPPORTED["archive"], {"zip:list"})
        self.assertNotIn("zip:extract", SUPPORTED["archive"])
        self.assertNotIn("zip:create", SUPPORTED["archive"])


if __name__ == "__main__":
    unittest.main()
