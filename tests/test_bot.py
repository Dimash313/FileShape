"""Validate handler import and basic user-facing menus without a bot token."""
import unittest

from aiogram.types import Chat, Document, Message, PhotoSize

from main import attachment, file_menu, size_allowed


class BotMenuTests(unittest.TestCase):
    def test_menus(self):
        pdf = file_menu("pdf")
        image = file_menu("image")
        self.assertTrue(any(button.callback_data == "pdf:merge" for row in pdf.inline_keyboard for button in row))
        self.assertTrue(any(button.callback_data == "img:PDF" for row in image.inline_keyboard for button in row))
        for kind, callback in [
            ("docx", "docx:txt"),
            ("txt", "txt:docx"),
            ("archive", "zip:extract"),
            ("other", "zip:create"),
        ]:
            with self.subTest(kind=kind):
                menu = file_menu(kind)
                actions = [button.callback_data for row in menu.inline_keyboard for button in row]
                self.assertIn(callback, actions)
                self.assertIn("zip:create", actions)

    def test_size_limit(self):
        self.assertTrue(size_allowed(20 * 1024 * 1024))
        self.assertFalse(size_allowed(20 * 1024 * 1024 + 1))
        self.assertFalse(size_allowed(None))

    def test_document_classification(self):
        from datetime import datetime, timezone
        message = Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=1, type="private"),
            document=Document(file_id="abc", file_unique_id="xyz", file_name="a.PDF", file_size=101),
        )
        document, suffix, kind, size = attachment(message)
        self.assertEqual((suffix, kind, size), (".pdf", "pdf", 101))


if __name__ == "__main__":
    unittest.main()
