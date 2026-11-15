"""Telegram image port regressions: dispatch, ownership and honest quota use.

The Telegram transport and image port are mocked here; real image parsing,
conversion, size limits and API worker paths are covered by other test suites.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main


USER_ID = 3371
BOT_TOKEN = "123456:TEST-IMAGE-PORT"
JOB_ID = "image-port-job"


class BotImagePortTests(unittest.IsolatedAsyncioTestCase):
    def make_callback(
        self,
        action="img:JPEG",
        *,
        owner=USER_ID,
        chat_id=USER_ID,
        photo=False,
        filename="input.png",
        size=1024,
        current_state=None,
    ):
        item = SimpleNamespace(file_id="image-file", file_size=size)
        if photo:
            origin = SimpleNamespace(
                document=None,
                photo=[item],
                audio=None,
                voice=None,
                from_user=SimpleNamespace(id=owner),
            )
        else:
            item.file_name = filename
            origin = SimpleNamespace(
                document=item,
                photo=None,
                audio=None,
                voice=None,
                from_user=SimpleNamespace(id=owner),
            )
        status = SimpleNamespace(delete=AsyncMock())
        message = SimpleNamespace(
            document=None,
            caption=None,
            from_user=SimpleNamespace(is_bot=True),
            reply_to_message=origin,
            chat=SimpleNamespace(type="private", id=chat_id),
            answer=AsyncMock(return_value=status),
            answer_document=AsyncMock(),
        )
        callback = SimpleNamespace(
            data=action,
            from_user=SimpleNamespace(id=USER_ID),
            message=message,
            answer=AsyncMock(),
        )
        state = SimpleNamespace(get_state=AsyncMock(return_value=current_state))

        async def download(file, *, destination):
            self.assertEqual(file.file_id, "image-file")
            Path(destination).write_bytes(b"mock image input")

        bot = SimpleNamespace(
            token=BOT_TOKEN,
            download=AsyncMock(side_effect=download),
        )
        return callback, bot, state

    async def test_all_image_conversions_use_shared_port_and_old_output_names(self):
        cases = (
            ("img:JPEG", "JPEG", "converted.jpg"),
            ("img:PNG", "PNG", "converted.png"),
            ("img:WEBP", "WEBP", "converted.webp"),
            ("img:PDF", "PDF", "converted.pdf"),
        )
        for action, fmt, name in cases:
            with self.subTest(action=action):
                callback, bot, state = self.make_callback(action)
                def convert(source, target, actual_format):
                    self.assertEqual(source.name, "source.png")
                    self.assertEqual(target.name, name)
                    self.assertEqual(actual_format, fmt)
                    target.write_bytes(b"mock converted result")
                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True) as authorize,
                    patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                                 return_value=JOB_ID) as reserve,
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "image_module") as module,
                ):
                    module.convert.side_effect = convert
                    await main.run_action(callback, bot, state)
                    module.convert.assert_called_once()
                    module.compress.assert_not_called()
                    module.bundle_as_pdf.assert_not_called()
                    authorize.assert_awaited_once()
                    reserve.assert_awaited_once_with(USER_ID, BOT_TOKEN)
                    settle.assert_awaited_once_with(
                        USER_ID, BOT_TOKEN, JOB_ID, True,
                    )
                callback.message.answer_document.assert_awaited_once()
                sent = callback.message.answer_document.await_args.kwargs
                self.assertTrue(sent["caption"].startswith("FileShape · "))
                buttons = [
                    button.callback_data
                    for row in sent["reply_markup"].inline_keyboard
                    for button in row
                ]
                self.assertIn("pdf:info" if fmt == "PDF" else "img:compress", buttons)
                bot.download.assert_awaited_once()
                callback.answer.assert_awaited_once()

    async def test_compression_uses_port_and_accepts_telegram_photo(self):
        callback, bot, state = self.make_callback("img:compress", photo=True)

        def compress(source, target):
            self.assertEqual(source.name, "source.jpg")
            self.assertEqual(target.name, "optimized.webp")
            target.write_bytes(b"mock optimized image")

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "image_module") as module,
        ):
            module.compress.side_effect = compress
            await main.run_action(callback, bot, state)
            module.compress.assert_called_once()
            module.convert.assert_not_called()
            module.bundle_as_pdf.assert_not_called()
            settle.assert_awaited_once_with(USER_ID, BOT_TOKEN, JOB_ID, True)
        callback.message.answer_document.assert_awaited_once()
        bot.download.assert_awaited_once()
        self.assertEqual(Path(callback.message.answer_document.await_args.args[0].path).name,
                         "optimized.webp")

    async def test_conversion_failure_refunds_and_reports_error(self):
        callback, bot, state = self.make_callback("img:PNG")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "image_module") as module,
        ):
            module.convert.side_effect = ValueError("broken image")
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER_ID, BOT_TOKEN, JOB_ID, False)
        callback.message.answer_document.assert_not_awaited()
        self.assertIn("broken image", callback.message.answer.await_args_list[-1].args[0])

    async def test_telegram_delivery_failure_refunds_without_fake_success(self):
        callback, bot, state = self.make_callback("img:JPEG")
        callback.message.answer_document.side_effect = OSError("transport failed")

        def convert(source, target, fmt):
            target.write_bytes(b"valid module output")

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "image_module") as module,
            patch.object(main.logger, "exception"),
        ):
            module.convert.side_effect = convert
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER_ID, BOT_TOKEN, JOB_ID, False)
        callback.message.answer_document.assert_awaited_once()
        self.assertIn(
            "Не удалось обработать файл",
            callback.message.answer.await_args_list[-1].args[0],
        )

    async def test_oversized_output_rejected_before_telegram_delivery(self):
        callback, bot, state = self.make_callback("img:PNG")

        def oversized(source, target, fmt):
            with target.open("wb") as output:
                output.truncate(main.MAX_OUTPUT_BYTES + 1)

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB_ID),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "image_module") as module,
        ):
            module.convert.side_effect = oversized
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER_ID, BOT_TOKEN, JOB_ID, False)
        callback.message.answer_document.assert_not_awaited()
        self.assertIn(
            "Result is too large",
            callback.message.answer.await_args_list[-1].args[0],
        )

    async def test_unauthorized_unsupported_and_large_inputs_do_no_work(self):
        cases = (
            self.make_callback(owner=USER_ID + 1),
            self.make_callback(chat_id=USER_ID + 1),
            self.make_callback(action="img:SVG"),
            self.make_callback(size=main.MAX_BYTES + 1),
            self.make_callback(size=None),
            self.make_callback(current_state="MergeState:collecting"),
        )
        for callback, bot, state in cases:
            with (
                self.subTest(action=callback.data, chat=callback.message.chat.id),
                patch.object(main, "Message", SimpleNamespace),
                patch.object(main, "allow_processing", new_callable=AsyncMock) as authorize,
                patch.object(main, "reserve_bot_operation",
                             new_callable=AsyncMock) as reserve,
                patch.object(main, "image_module") as module,
            ):
                await main.run_action(callback, bot, state)
                authorize.assert_not_awaited()
                reserve.assert_not_awaited()
                bot.download.assert_not_awaited()
                module.convert.assert_not_called()
                module.compress.assert_not_called()
                module.bundle_as_pdf.assert_not_called()
                callback.answer.assert_awaited_once()

    async def test_access_denial_precedes_download_and_quota_reservation(self):
        callback, bot, state = self.make_callback("img:compress")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=False) as authorize,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock) as reserve,
            patch.object(main, "image_module") as module,
        ):
            await main.run_action(callback, bot, state)
            authorize.assert_awaited_once()
            reserve.assert_not_awaited()
            bot.download.assert_not_awaited()
            module.convert.assert_not_called()
            module.compress.assert_not_called()
            module.bundle_as_pdf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
