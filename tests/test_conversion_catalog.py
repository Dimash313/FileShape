"""The conversion catalog must not change existing API action/suffix behavior."""
import unittest

from api import conversion_catalog
from api import server


class ConversionCatalogTests(unittest.TestCase):
    def test_api_uses_shared_catalog_objects(self):
        self.assertIs(server.SUPPORTED, conversion_catalog.SUPPORTED)
        self.assertIs(server.IMAGE_EXTENSIONS, conversion_catalog.IMAGE_EXTENSIONS)
        self.assertIs(server.file_kind, conversion_catalog.file_kind)

    def test_existing_action_allowlists_are_unchanged(self):
        self.assertEqual(conversion_catalog.SUPPORTED, {
            "image": {"img:JPEG", "img:PNG", "img:WEBP", "img:PDF", "img:compress"},
            "pdf": {"pdf:rotate", "pdf:first", "pdf:extract", "pdf:remove", "pdf:info"},
            "audio": {"audio:mp3", "audio:ogg", "audio:wav", "audio:info"},
            "docx": {"docx:txt", "docx:info"},
            "txt": {"txt:docx", "txt:info"},
            "archive": {"zip:list"},
        })
        self.assertNotIn("pdf:unsafe", conversion_catalog.SUPPORTED["pdf"])

    def test_suffix_routing_case_and_windows_paths(self):
        cases = {
            "report.PDF": ("pdf", ".pdf"),
            "photo.JpG": ("image", ".jpg"),
            "C:\\uploads\\photo.PNG": ("image", ".png"),
            "voice.MP3": ("audio", ".mp3"),
            "notes.DOCX": ("docx", ".docx"),
            "notes.TXT": ("txt", ".txt"),
            "work.ZIP": ("archive", ".zip"),
            "file.tar.gz": ("other", ".gz"),
            "no_extension": ("other", ""),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(conversion_catalog.file_kind(name), expected)
