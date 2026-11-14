"""Validate handler import and basic user-facing menus without a bot token."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram.types import Audio, Chat, Document, Message, Voice

from main import attachment, classify_extension, file_menu, miniapp_keyboard, send_result, size_allowed, home_keyboard, home_text, navigation_keyboard, back_keyboard, navigate, start


class BotMenuTests(unittest.TestCase):
    def test_navigation_and_honest_plan_status(self):
        with patch.dict("os.environ", {"MINIAPP_URL": ""}):
            home = home_keyboard()
            codes = [b.callback_data for row in home.inline_keyboard for b in row]
            self.assertEqual(codes, ["nav:tools", "nav:profile", "nav:plans", "nav:help"])
            self.assertIn("/menu", home_text())
        with patch.dict("os.environ", {"MINIAPP_URL": "https://example.com/studio"}):
            self.assertEqual(home_keyboard().inline_keyboard[0][0].web_app.url, "https://example.com/studio")
        codes = [b.callback_data for row in navigation_keyboard().inline_keyboard for b in row]
        self.assertEqual(len(set(codes)), 6)
        self.assertIn("nav:archive", codes)
        self.assertIn("nav:home", codes)
        self.assertIn("nav:tools", [b.callback_data for row in back_keyboard().inline_keyboard for b in row])

    def test_start_and_navigation(self):
        import asyncio
        async def check():
            message = type("FakeMessage", (), {
                "chat": type("Chat", (), {"type": "private"})(),
                "answer": AsyncMock(),
            })()
            state = type("State", (), {"clear": AsyncMock()})()
            await start(message, state)
            state.clear.assert_awaited_once()
            self.assertIn("nav:tools", [b.callback_data for row in message.answer.call_args.kwargs["reply_markup"].inline_keyboard for b in row])
            bot_message = type("BotMessage", (), {
                "chat": type("Chat", (), {"type": "private", "id": 123})(),
                "edit_text": AsyncMock(),
            })()
            from aiogram.types import Message as AiogramMessage
            # Handler checks Telegram's actual Message type; construct one with model validation.
            from datetime import datetime, timezone
            actual = AiogramMessage(message_id=1, date=datetime.now(timezone.utc),
                                     chat=Chat(id=123, type="private"), text="menu")
            with patch.object(AiogramMessage, "edit_text", new_callable=AsyncMock) as edit:
                callback = type("Callback", (), {
                    "message": actual, "from_user": type("User", (), {"id": 123})(),
                    "data": "nav:plans", "answer": AsyncMock(),
                })()
                await navigate(callback, state, SimpleNamespace(token='test-token'))
                self.assertIn("пока недоступны", edit.call_args.args[0])
                self.assertIn("Free: 10", edit.call_args.args[0])
                callback.answer.assert_awaited_once()
                callback.data = "nav:home"
                await navigate(callback, state, SimpleNamespace(token='test-token'))
                self.assertEqual(state.clear.await_count, 2)
                callback.data = "nav:unknown"
                await navigate(callback, state, SimpleNamespace(token='test-token'))
                self.assertEqual(edit.await_count, 2)
        asyncio.run(check())

    def test_miniapp_launch_only_with_https(self):
        with patch.dict("os.environ", {"MINIAPP_URL": ""}):
            self.assertIsNone(miniapp_keyboard())
        with patch.dict("os.environ", {"MINIAPP_URL": "http://invalid.example"}):
            self.assertIsNone(miniapp_keyboard())
        with patch.dict("os.environ", {"MINIAPP_URL": "https://example.com/studio"}):
            menu = miniapp_keyboard()
            self.assertIsNotNone(menu)
            self.assertEqual(menu.inline_keyboard[0][0].web_app.url, "https://example.com/studio")

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
