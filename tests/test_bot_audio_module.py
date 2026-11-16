"""Telegram audio contract regressions after the shared-module migration.

These handler tests exercise routing, isolation and quota settlement without
requiring Telegram or FFmpeg. Existing test_audio_tools.py exercises FFmpeg.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main


USER_ID = 1137
TOKEN = "123456:TEST_BOT_AUDIO"
JOB_ID = "audio-test-operation"


class TelegramAudioModuleTests(unittest.IsolatedAsyncioTestCase):
    def make_callback(self, action="audio:mp3", *, owner=USER_ID, chat_id=USER_ID):
        uploaded = SimpleNamespace(
            audio=SimpleNamespace(
                file_id="owned_audio", file_size=1024,
                file_name="recording.wav", mime_type="audio/wav",
            ),
            document=None, photo=None, voice=None,
            from_user=SimpleNamespace(id=owner),
        )
        status = SimpleNamespace(delete=AsyncMock())
        message = SimpleNamespace(
            document=None, caption=None,
            from_user=SimpleNamespace(is_bot=True),
            reply_to_message=uploaded,
            chat=SimpleNamespace(type="private", id=chat_id),
            answer=AsyncMock(return_value=status),
            answer_document=AsyncMock(),
        )
        callback = SimpleNamespace(
            data=action, from_user=SimpleNamespace(id=USER_ID),
            message=message, answer=AsyncMock(),
        )
        state = SimpleNamespace(get_state=AsyncMock(return_value=None))
        async def download(file, *, destination):
            self.assertEqual(file.file_id, "owned_audio")
            Path(destination).write_bytes(b"not decoded: adapter mocked")
        bot = SimpleNamespace(token=TOKEN, download=AsyncMock(side_effect=download))
        return callback, bot, state

    async def test_audio_conversion_uses_module_and_keeps_result_naming(self):
        for action, extension in (("audio:mp3", "mp3"), ("audio:ogg", "ogg"),
                                  ("audio:wav", "wav")):
            with self.subTest(action=action):
                callback, bot, state = self.make_callback(action)
                def produce(source, target, fmt):
                    self.assertEqual(source.name, "source.wav")
                    self.assertEqual(target.name, f"audio.{extension}")
                    self.assertEqual(fmt, extension)
                    target.write_bytes(b"transformed")
                    return {"seconds": 1.0, "codec": "pcm"}
                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True) as allow,
                    patch.object(main, "reserve_bot_operation",
                                 new_callable=AsyncMock, return_value=JOB_ID) as reserve,
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "audio_module") as module,
                ):
                    module.convert.side_effect = produce
                    await main.run_action(callback, bot, state)
                    module.convert.assert_called_once()
                    module.probe.assert_not_called()
                    allow.assert_awaited_once()
                    reserve.assert_awaited_once_with(USER_ID, TOKEN)
                    settle.assert_awaited_once_with(USER_ID, TOKEN, JOB_ID, True)
                callback.message.answer_document.assert_awaited_once()
                kwargs = callback.message.answer_document.await_args.kwargs
                self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data,
                                 "audio:mp3")
                bot.download.assert_awaited_once()
                callback.answer.assert_awaited_once()

    async def test_audio_info_uses_module_and_preserves_bot_text(self):
        callback, bot, state = self.make_callback("audio:info")
        info = {"seconds": 3.4, "codec": "pcm_s16le"}
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "audio_module") as module,
        ):
            module.probe.return_value = info
            await main.run_action(callback, bot, state)
            module.probe.assert_called_once()
            module.convert.assert_not_called()
            settle.assert_awaited_once_with(USER_ID, TOKEN, JOB_ID, True)
        text = callback.message.answer.await_args_list[-1].args[0]
        self.assertIn("3.4 сек.", text)
        self.assertIn("pcm_s16le", text)
        callback.message.answer_document.assert_not_awaited()

    async def test_failed_audio_conversion_refunds_and_does_not_send_file(self):
        callback, bot, state = self.make_callback()
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "audio_module") as module,
        ):
            module.convert.side_effect = ValueError("invalid audio")
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER_ID, TOKEN, JOB_ID, False)
        callback.message.answer_document.assert_not_awaited()
        self.assertIn("invalid audio", callback.message.answer.await_args_list[-1].args[0])

    async def test_failed_telegram_delivery_refunds(self):
        callback, bot, state = self.make_callback()
        callback.message.answer_document.side_effect = OSError("send failed")
        def produce(source, target, fmt):
            target.write_bytes(b"output")
            return {"seconds": 1.0, "codec": "pcm"}
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "audio_module") as module,
            patch.object(main.logger, "exception"),
        ):
            module.convert.side_effect = produce
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER_ID, TOKEN, JOB_ID, False)
        self.assertIn("Не удалось обработать файл",
                      callback.message.answer.await_args_list[-1].args[0])

    async def test_foreign_user_or_unsupported_action_never_dispatches(self):
        for callback, bot, state in (
            self.make_callback(owner=2222),
            self.make_callback(chat_id=2222),
            self.make_callback(action="audio:unsupported"),
        ):
            with (
                self.subTest(action=callback.data, chat=callback.message.chat.id,
                             owner=callback.message.reply_to_message.from_user.id),
                patch.object(main, "Message", SimpleNamespace),
                patch.object(main, "allow_processing", new_callable=AsyncMock) as allow,
                patch.object(main, "reserve_bot_operation",
                             new_callable=AsyncMock) as reserve,
                patch.object(main, "audio_module") as module,
            ):
                await main.run_action(callback, bot, state)
                allow.assert_not_awaited()
                reserve.assert_not_awaited()
                bot.download.assert_not_awaited()
                module.probe.assert_not_called()
                module.convert.assert_not_called()
                callback.answer.assert_awaited_once()
                self.assertTrue(callback.answer.await_args.kwargs["show_alert"])


if __name__ == "__main__":
    unittest.main()
