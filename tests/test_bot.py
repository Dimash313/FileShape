"""Validate handler import and basic user-facing menus without a bot token."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram.types import Audio, Chat, Document, Message, Voice

from main import attachment, classify_extension, file_menu, send_result, size_allowed


class BotMenuTests(unittest.TestCase):
    def test_menus(self):
        pdf = file_menu("pdf")
        image = file_menu("image")
        self.assertTrue(any(button.callback_data == "pdf:merge" for row in pdf.inline_keyboard for button in row))
        self.assertTrue(any(button.callback_data == "pdf:remove" for row in pdf.inline_keyboard for button in row))
        self.assertTrue(any(button.callback_data == "img:PDF" for row in image.inline_keyboard for button in row))
        for kind, callback in [
            ("docx", "docx:txt"),
            ("txt", "txt:docx"),
            ("archive", "zip:extract"),
            ("other", "zip:create"),
            ("audio", "audio:mp3"),
        ]:
            with self.subTest(kind=kind):
                menu = file_menu(kind)
                actions = [button.callback_data for row in menu.inline_keyboard for button in row]
                self.assertIn(callback, actions)
                self.assertIn("zip:create", actions)

    def test_result_formats(self):
        self.assertEqual(classify_extension(".PDF"), "pdf")
        self.assertEqual(classify_extension(".zip"), "archive")
        self.assertEqual(classify_extension(".mp3"), "audio")
        self.assertEqual(classify_extension(".unknown"), "other")

    async def _send_result(self, size):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.pdf"
            with path.open("wb") as output:
                output.truncate(size)
            message = type("FakeMessage", (), {"answer_document": AsyncMock()})()
            await send_result(message, path)
            return message.answer_document.call_args.kwargs

    def test_result_has_follow_up_actions(self):
        import asyncio
        args = asyncio.run(self._send_result(1024))
        self.assertIn("FileShape", args["caption"])
        actions = [b.callback_data for row in args["reply_markup"].inline_keyboard for b in row]
        self.assertIn("pdf:rotate", actions)

    def test_large_result_disables_follow_up(self):
        import asyncio
        args = asyncio.run(self._send_result(21 * 1024 * 1024))
        self.assertIsNone(args["reply_markup"])

    def test_size_limit(self):
        self.assertTrue(size_allowed(20 * 1024 * 1024))
        self.assertFalse(size_allowed(20 * 1024 * 1024 + 1))
        self.assertFalse(size_allowed(None))

    def test_audio_classification(self):
        from datetime import datetime, timezone
        params = {
            "message_id": 2,
            "date": datetime.now(timezone.utc),
            "chat": Chat(id=1, type="private"),
        }
        audio_message = Message(
            **params,
            audio=Audio(
                file_id="a", file_unique_id="b", duration=1,
                file_name="track.MP3", file_size=1024,
            ),
        )
        self.assertEqual(attachment(audio_message)[1:3], (".mp3", "audio"))
        voice_message = Message(
            **params,
            voice=Voice(file_id="c", file_unique_id="d", duration=2, file_size=100),
        )
        self.assertEqual(attachment(voice_message)[1:3], (".ogg", "audio"))

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
