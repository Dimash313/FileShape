"""Bot PDF adapter regressions: bot controls, module calls, and quota safety.

These are behavioral wiring tests with mocked Telegram transport. The real
PDF data-path is exercised in test_pdf_module_contract.py and test_file_tools.py.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main


USER = 1501
TOKEN = "123456:PDF-PORT-TEST"
JOB = "test-pdf-job"


def pdf_upload(*, owner=USER):
    return SimpleNamespace(
        document=SimpleNamespace(file_id="pdf-1", file_size=1024,
                                 file_name="original.pdf"),
        audio=None, voice=None, photo=None,
        from_user=SimpleNamespace(id=owner),
    )


def make_bot():
    async def download(file, *, destination):
        Path(destination).write_bytes(b"pdf fixture replaced at module boundary")

    return SimpleNamespace(
        token=TOKEN,
        download=AsyncMock(side_effect=download),
    )


def make_message(*, origin=None, chat_id=USER):
    status = SimpleNamespace(delete=AsyncMock())
    return SimpleNamespace(
        document=None, caption=None,
        from_user=SimpleNamespace(id=USER, is_bot=True),
        reply_to_message=origin,
        chat=SimpleNamespace(type="private", id=chat_id),
        answer=AsyncMock(return_value=status),
        answer_document=AsyncMock(),
        message_id=13,
    )


class BotPdfPortTests(unittest.IsolatedAsyncioTestCase):
    def callback(self, action, *, owner=USER, chat_id=USER):
        message = make_message(origin=pdf_upload(owner=owner), chat_id=chat_id)
        callback = SimpleNamespace(
            data=action, from_user=SimpleNamespace(id=USER),
            message=message, answer=AsyncMock(),
        )
        state = SimpleNamespace(get_state=AsyncMock(return_value=None))
        return callback, make_bot(), state

    async def test_info_rotate_and_first_page_use_pdf_port(self):
        for action, method, expected_name in (
            ("pdf:info", "count_pages", None),
            ("pdf:rotate", "rotate", "rotated.pdf"),
            ("pdf:first", "extract", "first_page.pdf"),
        ):
            with self.subTest(action=action):
                callback, bot, state = self.callback(action)
                def write_pdf(source, target, value):
                    self.assertEqual(source.name, "source.pdf")
                    self.assertEqual(target.name, expected_name)
                    self.assertEqual(value, "1" if action == "pdf:first" else 90)
                    target.write_bytes(b"mock PDF")
                    return 1
                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True) as allow,
                    patch.object(main, "reserve_bot_operation",
                                 new_callable=AsyncMock, return_value=JOB) as reserve,
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "pdf_module") as pdf,
                ):
                    if action == "pdf:info":
                        pdf.count_pages.return_value = 7
                    else:
                        getattr(pdf, method).side_effect = write_pdf
                    await main.run_action(callback, bot, state)
                    allow.assert_awaited_once()
                    reserve.assert_awaited_once_with(USER, TOKEN)
                    settle.assert_awaited_once_with(USER, TOKEN, JOB, True)
                    chosen = getattr(pdf, method)
                    chosen.assert_called_once()
                    for other in ("count_pages", "extract", "rotate", "remove", "merge"):
                        if other != method:
                            getattr(pdf, other).assert_not_called()
                if action == "pdf:info":
                    self.assertIn("7", callback.message.answer.await_args_list[-1].args[0])
                    callback.message.answer_document.assert_not_awaited()
                else:
                    callback.message.answer_document.assert_awaited_once()
                    self.assertEqual(
                        callback.message.answer_document.await_args.kwargs["reply_markup"]
                        .inline_keyboard[0][0].callback_data, "pdf:info",
                    )
                bot.download.assert_awaited_once()
                callback.answer.assert_awaited_once()

    async def test_page_selection_extract_remove_and_exact_filenames(self):
        for mode, method, filename in (
            ("pdf:extract", "extract", "pages.pdf"),
            ("pdf:remove", "remove", "without_pages.pdf"),
        ):
            with self.subTest(mode=mode):
                message = make_message()
                message.from_user = SimpleNamespace(id=USER)
                state = SimpleNamespace(
                    get_data=AsyncMock(return_value={"file_id": "pdf-pages", "pdf_mode": mode}),
                    clear=AsyncMock(),
                )
                bot = make_bot()
                def write_pdf(source, target, selection):
                    self.assertEqual(source.name, "source.pdf")
                    self.assertEqual(target.name, filename)
                    self.assertEqual(selection, "1,3")
                    target.write_bytes(b"mock PDF")
                    return 2
                with (
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True) as allow,
                    patch.object(main, "reserve_bot_operation",
                                 new_callable=AsyncMock, return_value=JOB) as reserve,
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "pdf_module") as pdf,
                ):
                    getattr(pdf, method).side_effect = write_pdf
                    message.text = "1,3"
                    await main.extract_by_range(message, bot, state)
                    getattr(pdf, method).assert_called_once()
                    for other in ("extract", "remove", "rotate", "merge", "count_pages"):
                        if other != method:
                            getattr(pdf, other).assert_not_called()
                    allow.assert_awaited_once()
                    reserve.assert_awaited_once_with(USER, TOKEN)
                    settle.assert_awaited_once_with(USER, TOKEN, JOB, True)
                bot.download.assert_awaited_once_with("pdf-pages", destination=unittest.mock.ANY)
                message.answer_document.assert_awaited_once()
                state.clear.assert_awaited_once()
                self.assertIn("2", message.answer_document.await_args.kwargs["caption"])

    async def test_merge_uses_port_and_preserves_order_and_settlement(self):
        message = make_message()
        message.from_user = SimpleNamespace(id=USER)
        state = SimpleNamespace(
            get_state=AsyncMock(return_value=main.MergeState.collecting.state),
            get_data=AsyncMock(return_value={"pdfs": [
                {"file_id": "first", "size": 1024},
                {"file_id": "second", "size": 1024},
            ]}),
            clear=AsyncMock(),
        )
        bot = make_bot()
        def merge(paths, target):
            self.assertEqual([p.name for p in paths], ["part_0.pdf", "part_1.pdf"])
            self.assertEqual(target.name, "merged.pdf")
            target.write_bytes(b"mock PDF")
            return 5
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True) as allow,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB) as reserve,
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "pdf_module") as pdf,
        ):
            pdf.merge.side_effect = merge
            await main.run_merge(message, bot, state, USER)
            pdf.merge.assert_called_once()
            allow.assert_awaited_once()
            reserve.assert_awaited_once_with(USER, TOKEN)
            settle.assert_awaited_once_with(USER, TOKEN, JOB, True)
        state.clear.assert_awaited_once()
        self.assertEqual([c.args[0] for c in bot.download.await_args_list],
                         ["first", "second"])
        message.answer_document.assert_awaited_once()
        self.assertIn("5 стр.", message.answer_document.await_args.kwargs["caption"])

    async def test_merge_error_refunds_and_sends_no_result(self):
        message = make_message()
        message.from_user = SimpleNamespace(id=USER)
        state = SimpleNamespace(
            get_state=AsyncMock(return_value=main.MergeState.collecting.state),
            get_data=AsyncMock(return_value={"pdfs": [
                {"file_id": "first", "size": 1024},
                {"file_id": "second", "size": 1024},
            ]}),
            clear=AsyncMock(),
        )
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "pdf_module") as pdf,
        ):
            pdf.merge.side_effect = ValueError("broken PDF")
            await main.run_merge(message, make_bot(), state, USER)
            settle.assert_awaited_once_with(USER, TOKEN, JOB, False)
        message.answer_document.assert_not_awaited()
        self.assertIn("broken PDF", message.answer.await_args_list[-1].args[0])

    async def test_page_selection_failure_refunds_without_losing_retry_state(self):
        message = make_message()
        message.from_user = SimpleNamespace(id=USER)
        message.text = "2-1"
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={"file_id": "pdf-pages",
                                             "pdf_mode": "pdf:extract"}),
            clear=AsyncMock(),
        )
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "pdf_module") as pdf,
        ):
            pdf.extract.side_effect = ValueError("Bad range")
            await main.extract_by_range(message, make_bot(), state)
            settle.assert_awaited_once_with(USER, TOKEN, JOB, False)
        message.answer_document.assert_not_awaited()
        state.clear.assert_not_awaited()
        self.assertIn("Bad range", message.answer.await_args_list[-1].args[0])

    async def test_telegram_pdf_delivery_failure_refunds_quota(self):
        callback, bot, state = self.callback("pdf:rotate")
        callback.message.answer_document.side_effect = OSError("Telegram unavailable")

        def rotate(source, target, degrees):
            self.assertEqual(degrees, 90)
            target.write_bytes(b"mock PDF")
            return 1

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock, return_value=JOB),
            patch.object(main, "settle_bot_operation",
                         new_callable=AsyncMock) as settle,
            patch.object(main, "pdf_module") as pdf,
            patch.object(main.logger, "exception"),
        ):
            pdf.rotate.side_effect = rotate
            await main.run_action(callback, bot, state)
            settle.assert_awaited_once_with(USER, TOKEN, JOB, False)
        callback.message.answer_document.assert_awaited_once()
        self.assertIn("Не удалось обработать файл",
                      callback.message.answer.await_args_list[-1].args[0])

    async def test_denied_pdf_merge_does_not_consume_quota_or_download(self):
        message = make_message()
        state = SimpleNamespace(
            get_state=AsyncMock(return_value=main.MergeState.collecting.state),
            get_data=AsyncMock(return_value={"pdfs": [
                {"file_id": "first", "size": 1024},
                {"file_id": "second", "size": 1024},
            ]}),
            clear=AsyncMock(),
        )
        bot = make_bot()
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=False) as allow,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock) as reserve,
            patch.object(main, "pdf_module") as pdf,
        ):
            await main.run_merge(message, bot, state, USER)
            allow.assert_awaited_once()
            reserve.assert_not_awaited()
            pdf.merge.assert_not_called()
        bot.download.assert_not_awaited()
        state.clear.assert_not_awaited()
        message.answer_document.assert_not_awaited()

    async def test_foreign_or_unknown_callback_does_not_download_or_reserve(self):
        cases = (
            self.callback("pdf:info", owner=USER + 1),
            self.callback("pdf:rotate", chat_id=USER + 1),
            self.callback("pdf:madeup"),
        )
        for callback, bot, state in cases:
            with (
                self.subTest(action=callback.data,
                             chat=callback.message.chat.id),
                patch.object(main, "Message", SimpleNamespace),
                patch.object(main, "allow_processing",
                             new_callable=AsyncMock) as allow,
                patch.object(main, "reserve_bot_operation",
                             new_callable=AsyncMock) as reserve,
                patch.object(main, "pdf_module") as pdf,
            ):
                await main.run_action(callback, bot, state)
                allow.assert_not_awaited()
                reserve.assert_not_awaited()
                bot.download.assert_not_awaited()
                for method in ("count_pages", "extract", "rotate", "remove", "merge"):
                    getattr(pdf, method).assert_not_called()
                callback.answer.assert_awaited_once()
                self.assertTrue(callback.answer.await_args.kwargs["show_alert"])

    async def test_denied_processing_does_not_reserve_or_call_pdf_module(self):
        callback, bot, state = self.callback("pdf:info")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=False) as allow,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock) as reserve,
            patch.object(main, "pdf_module") as pdf,
        ):
            await main.run_action(callback, bot, state)
            allow.assert_awaited_once()
            reserve.assert_not_awaited()
            bot.download.assert_not_awaited()
            pdf.count_pages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
