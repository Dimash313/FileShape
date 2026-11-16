"""Telegram DOCX/TXT domain port: handler, ownership and quota regressions.

These tests mock Telegram transport and the document port. Real DOCX/TXT
parsing and size-limit tests are in test_document_module_contract.py and
test_document_tools.py. No external Telegram API or token is required.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main


USER = 4419
TOKEN = "123456:TEST_DOCUMENT_PORT"
OPERATION = "docx-txt-port-test"


class BotDocumentPortTests(unittest.IsolatedAsyncioTestCase):
    def make_callback(
        self, action="docx:info", *, owner=USER, chat_id=USER,
        filename="input.docx", file_size=1024, busy=None,
    ):
        document = SimpleNamespace(
            file_id="owned-doc", file_name=filename, file_size=file_size,
        )
        upload = SimpleNamespace(
            document=document, audio=None, photo=None, voice=None,
            from_user=SimpleNamespace(id=owner),
        )
        status = SimpleNamespace(delete=AsyncMock())
        message = SimpleNamespace(
            document=None, caption=None,
            from_user=SimpleNamespace(is_bot=True),
            reply_to_message=upload,
            chat=SimpleNamespace(type="private", id=chat_id),
            answer=AsyncMock(return_value=status),
            answer_document=AsyncMock(),
        )
        callback = SimpleNamespace(
            data=action, message=message,
            from_user=SimpleNamespace(id=USER),
            answer=AsyncMock(),
        )
        state = SimpleNamespace(get_state=AsyncMock(return_value=busy))

        async def download(file, *, destination):
            self.assertEqual(file.file_id, "owned-doc")
            Path(destination).write_bytes(b"source fixture: port mocked")

        bot = SimpleNamespace(
            token=TOKEN,
            download=AsyncMock(side_effect=download),
        )
        return callback, bot, state

    async def test_docx_and_text_information_keep_exact_text_and_shape(self):
        cases = (
            ("docx:info", "input.docx", "inspect_docx",
             {"paragraphs": 4, "tables": 2, "characters": 38},
             "📝 DOCX: абзацев 4, таблиц 2, символов 38."),
            ("txt:info", "input.txt", "inspect_text",
             {"lines": 9, "characters": 99},
             "📝 TXT: строк 9, символов 99."),
        )
        for action, filename, method, result, expected in cases:
            with self.subTest(action=action):
                callback, bot, state = self.make_callback(
                    action, filename=filename,
                )
                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing",
                                 new_callable=AsyncMock, return_value=True) as access,
                    patch.object(main, "reserve_bot_operation",
                                 new_callable=AsyncMock,
                                 return_value=OPERATION) as reserve,
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "document_module") as documents,
                ):
                    getattr(documents, method).return_value = result
                    await main.run_action(callback, bot, state)
                    getattr(documents, method).assert_called_once()
                    args = getattr(documents, method).call_args.args
                    self.assertEqual(args[0].name, "source" + Path(filename).suffix)
                    for other in ("inspect_docx", "inspect_text", "to_text", "to_docx"):
                        if other != method:
                            getattr(documents, other).assert_not_called()
                    access.assert_awaited_once()
                    reserve.assert_awaited_once_with(USER, TOKEN)
                    settle.assert_awaited_once_with(USER, TOKEN, OPERATION, True)
                callback.message.answer_document.assert_not_awaited()
                self.assertEqual(callback.message.answer.await_args_list[-1].args[0],
                                 expected)
                callback.answer.assert_awaited_once()
                bot.download.assert_awaited_once()

    async def test_both_conversions_preserve_output_names_and_button_menus(self):
        cases = (
            ("docx:txt", "input.docx", "to_text",
             "document.txt", "txt:info"),
            ("txt:docx", "input.txt", "to_docx",
             "document.docx", "docx:info"),
        )
        for action, filename, method, output_name, expected_button in cases:
            with self.subTest(action=action):
                callback, bot, state = self.make_callback(action, filename=filename)

                def transform(source, target):
                    self.assertEqual(source.name, "source" + Path(filename).suffix)
                    self.assertEqual(target.name, output_name)
                    target.write_bytes(b"transformed file - document port mocked")
                    return {"characters": 15}

                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing",
                                 new_callable=AsyncMock, return_value=True),
                    patch.object(main, "reserve_bot_operation",
                                 new_callable=AsyncMock, return_value=OPERATION),
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "document_module") as documents,
                ):
                    getattr(documents, method).side_effect = transform
                    await main.run_action(callback, bot, state)
                    getattr(documents, method).assert_called_once()
                    for other in ("inspect_docx", "inspect_text", "to_text", "to_docx"):
                        if other != method:
                            getattr(documents, other).assert_not_called()
                    settle.assert_awaited_once_with(USER, TOKEN, OPERATION, True)
                sent = callback.message.answer_document
                sent.assert_awaited_once()
                self.assertEqual(Path(sent.await_args.args[0].path).name, output_name)
                self.assertEqual(sent.await_args.kwargs["caption"],
                                 "FileShape · ✅ Готово · FileShape")
                buttons = [
                    button.callback_data
                    for row in sent.await_args.kwargs["reply_markup"].inline_keyboard
                    for button in row
                ]
                self.assertIn(expected_button, buttons)
                bot.download.assert_awaited_once()

    async def test_invalid_document_refunds_and_does_not_send_result(self):
        callback, bot, state = self.make_callback("docx:txt")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "document_module") as documents,
        ):
            documents.to_text.side_effect = ValueError("Повреждённый DOCX")
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)
        callback.message.answer_document.assert_not_awaited()
        self.assertIn("Повреждённый DOCX",
                      callback.message.answer.await_args_list[-1].args[0])

    async def test_telegram_send_failure_refunds_even_when_conversion_finished(self):
        callback, bot, state = self.make_callback("txt:docx", filename="input.txt")
        callback.message.answer_document.side_effect = OSError("send unavailable")

        def to_docx(source, target):
            target.write_bytes(b"processed document")
            return {"lines": 1, "characters": 1}

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "document_module") as documents,
            patch.object(main.logger, "exception"),
        ):
            documents.to_docx.side_effect = to_docx
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)
        callback.message.answer_document.assert_awaited_once()
        self.assertIn("Не удалось обработать файл",
                      callback.message.answer.await_args_list[-1].args[0])

    async def test_info_message_failure_refunds(self):
        callback, bot, state = self.make_callback("txt:info", filename="input.txt")
        status = callback.message.answer.return_value

        async def response(text, **kwargs):
            if text.startswith("📝 TXT:"):
                raise OSError("message unavailable")
            return status

        callback.message.answer.side_effect = response
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "document_module") as documents,
            patch.object(main.logger, "exception"),
        ):
            documents.inspect_text.return_value = {"lines": 1, "characters": 1}
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)

    async def test_foreign_user_invalid_action_busy_and_oversize_do_not_process(self):
        cases = (
            self.make_callback(owner=USER + 1),
            self.make_callback(chat_id=USER + 1),
            self.make_callback(action="docx:remove"),
            self.make_callback(action="txt:unknown", filename="input.txt"),
            self.make_callback(action="txt:docx", filename="input.docx"),
            self.make_callback(file_size=main.MAX_BYTES + 1),
            self.make_callback(file_size=None),
            self.make_callback(busy="ExtractState:waiting_for_pages"),
        )
        for callback, bot, state in cases:
            with (
                self.subTest(action=callback.data, chat=callback.message.chat.id),
                patch.object(main, "Message", SimpleNamespace),
                patch.object(main, "allow_processing",
                             new_callable=AsyncMock) as access,
                patch.object(main, "reserve_bot_operation",
                             new_callable=AsyncMock) as reserve,
                patch.object(main, "document_module") as documents,
            ):
                await main.run_action(callback, bot, state)
                access.assert_not_awaited()
                reserve.assert_not_awaited()
                bot.download.assert_not_awaited()
                for method in ("inspect_docx", "inspect_text", "to_text", "to_docx"):
                    getattr(documents, method).assert_not_called()
                callback.answer.assert_awaited_once()

    async def test_access_denial_happens_before_download_and_quota(self):
        callback, bot, state = self.make_callback("docx:info")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=False) as access,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock) as reserve,
            patch.object(main, "document_module") as documents,
        ):
            await main.run_action(callback, bot, state)
            access.assert_awaited_once()
            reserve.assert_not_awaited()
            bot.download.assert_not_awaited()
            for method in ("inspect_docx", "inspect_text", "to_text", "to_docx"):
                getattr(documents, method).assert_not_called()


if __name__ == "__main__":
    unittest.main()
