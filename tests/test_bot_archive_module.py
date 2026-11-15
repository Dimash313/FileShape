"""Telegram ZIP archive domain-port contract and operation safety tests.

Fake Telegram traffic and mocked ZIP adapter here; real ZIP parser,
traversal, size and decompression regressions live in
test_archive_module_contract.py and test_archive_tools.py.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import main


USER = 5519
TOKEN = "123456:TEST-ZIP-PORT"
OPERATION = "archive-operation-id"


def fake_bot():
    async def download(file, *, destination):
        Path(destination).write_bytes(b"fixture content")

    return SimpleNamespace(
        token=TOKEN,
        download=AsyncMock(side_effect=download),
    )


def fake_message(*, chat_id=USER, owner=USER):
    status = SimpleNamespace(delete=AsyncMock())
    return SimpleNamespace(
        document=None,
        caption=None,
        from_user=SimpleNamespace(id=owner, is_bot=True),
        reply_to_message=None,
        chat=SimpleNamespace(type="private", id=chat_id),
        answer=AsyncMock(return_value=status),
        answer_document=AsyncMock(),
    )


def fake_callback(action, *, chat_id=USER, owner=USER,
                  filename="source.zip", size=1024, busy=None):
    source = SimpleNamespace(
        document=SimpleNamespace(
            file_id="source-archive",
            file_name=filename,
            file_size=size,
        ),
        photo=None, audio=None, voice=None,
        from_user=SimpleNamespace(id=owner),
    )
    message = fake_message(chat_id=chat_id)
    message.reply_to_message = source
    callback = SimpleNamespace(
        data=action, message=message,
        from_user=SimpleNamespace(id=USER),
        answer=AsyncMock(),
    )
    state = SimpleNamespace(
        get_state=AsyncMock(return_value=busy),
        set_state=AsyncMock(),
        update_data=AsyncMock(),
        clear=AsyncMock(),
    )
    return callback, fake_bot(), state


def zip_bundle(*, count=2, state=None, chat_id=USER):
    items = [
        {"file_id": f"item-{i}", "size": 128, "name": name}
        for i, name in enumerate(
            ("foo.txt", "docs/foo.txt", "other.png", "paper.pdf", "music-free.txt")[:count]
        )
    ]
    message = fake_message(chat_id=chat_id, owner=USER)
    message.from_user.is_bot = False
    fsm = SimpleNamespace(
        get_state=AsyncMock(
            return_value=main.ZipState.collecting.state if state is None else state,
        ),
        get_data=AsyncMock(return_value={"zip_files": items}),
        clear=AsyncMock(),
    )
    return message, fake_bot(), fsm, items


class BotArchivePortTests(unittest.IsolatedAsyncioTestCase):
    async def test_zip_list_uses_shared_port_and_preserves_user_text(self):
        callback, bot, fsm = fake_callback("zip:list")
        info = {"files": 4, "bytes": 4096, "names": ["first.txt", "docs/second.txt"]}
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True) as allow,
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION) as reserve,
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "archive_module") as archive,
        ):
            archive.inspect.return_value = info
            await main.run_action(callback, bot, fsm)
            archive.inspect.assert_called_once()
            self.assertEqual(archive.inspect.call_args.args[0].name, "source.zip")
            archive.extract.assert_not_called()
            archive.create.assert_not_called()
            allow.assert_awaited_once()
            reserve.assert_awaited_once_with(USER, TOKEN)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, True)
        callback.message.answer_document.assert_not_awaited()
        output = callback.message.answer.await_args_list[-1].args[0]
        self.assertIn("ZIP: файлов 4", output)
        self.assertIn("≈ 4 КБ", output)
        self.assertIn("• docs/second.txt", output)
        bot.download.assert_awaited_once()
        callback.answer.assert_awaited_once()

    async def test_zip_extract_uses_port_preserves_order_and_sends_two_results(self):
        callback, bot, fsm = fake_callback("zip:extract")

        def extract(source, folder):
            self.assertEqual(source.name, "source.zip")
            files = []
            for name in ("01_first.txt", "02_second.txt"):
                file = folder / name
                file.write_bytes(name.encode("utf-8"))
                files.append((file, name))
            return files

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "archive_module") as archive,
        ):
            archive.extract.side_effect = extract
            await main.run_action(callback, bot, fsm)
            archive.extract.assert_called_once()
            archive.inspect.assert_not_called()
            archive.create.assert_not_called()
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, True)
        self.assertEqual(callback.message.answer_document.await_count, 2)
        delivered = callback.message.answer_document.await_args_list
        self.assertEqual([Path(call.args[0].path).name for call in delivered],
                         ["01_first.txt", "02_second.txt"])
        self.assertTrue(all(
            call.kwargs["caption"].startswith("FileShape · 📂 ")
            for call in delivered
        ))
        for call in delivered:
            buttons = [
                button.callback_data
                for row in call.kwargs["reply_markup"].inline_keyboard
                for button in row
            ]
            self.assertIn("txt:info", buttons)

    async def test_zip_create_menu_starts_fsm_without_reservation_or_download(self):
        callback, bot, fsm = fake_callback("zip:create", filename="image.png")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True) as allow,
            patch.object(main, "reserve_bot_operation",
                         new_callable=AsyncMock) as reserve,
            patch.object(main, "archive_module") as archive,
        ):
            await main.run_action(callback, bot, fsm)
            allow.assert_awaited_once()
            reserve.assert_not_awaited()
            archive.create.assert_not_called()
            bot.download.assert_not_awaited()
        fsm.set_state.assert_awaited_once_with(main.ZipState.collecting)
        fsm.update_data.assert_awaited_once_with(
            zip_files=[{"file_id": "source-archive", "size": 1024, "name": "image.png"}]
        )
        self.assertIn("Создание ZIP · 1/5", callback.message.answer.await_args.args[0])

    async def test_zip_bundle_preserves_order_names_and_telegram_result(self):
        message, bot, fsm, items = zip_bundle(count=3)
        expected_names = [item["name"] for item in items]

        def create(inputs, target):
            self.assertEqual(target.name, "fileshape.zip")
            self.assertEqual([name for _file, name in inputs], expected_names)
            self.assertEqual([p.name for p, _name in inputs],
                             ["item_0", "item_1", "item_2"])
            self.assertTrue(all(p.exists() for p, _name in inputs))
            target.write_bytes(b"PK mock zip")
            return len(inputs)

        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True) as allow,
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION) as reserve,
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "archive_module") as archive,
        ):
            archive.create.side_effect = create
            await main.run_zip_bundle(message, bot, fsm, USER)
            archive.create.assert_called_once()
            archive.inspect.assert_not_called()
            archive.extract.assert_not_called()
            allow.assert_awaited_once_with(message, bot, USER)
            reserve.assert_awaited_once_with(USER, TOKEN)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, True)
        self.assertEqual(bot.download.await_count, 3)
        self.assertEqual([call.args[0] for call in bot.download.await_args_list],
                         [item["file_id"] for item in items])
        message.answer_document.assert_awaited_once()
        sent = message.answer_document.await_args
        self.assertEqual(Path(sent.args[0].path).name, "fileshape.zip")
        self.assertIn("ZIP из 3 файлов", sent.kwargs["caption"])
        self.assertEqual(sent.kwargs["reply_markup"].inline_keyboard[0][0].callback_data,
                         "zip:list")
        fsm.clear.assert_awaited_once()

    async def test_list_and_extract_failures_refund_without_success(self):
        for action, method in (("zip:list", "inspect"), ("zip:extract", "extract")):
            with self.subTest(action=action):
                callback, bot, fsm = fake_callback(action)
                with (
                    patch.object(main, "Message", SimpleNamespace),
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True),
                    patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                                 return_value=OPERATION),
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "archive_module") as archive,
                ):
                    getattr(archive, method).side_effect = ValueError("unsafe ZIP")
                    await main.run_action(callback, bot, fsm)
                    settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)
                callback.message.answer_document.assert_not_awaited()
                self.assertIn("unsafe ZIP", callback.message.answer.await_args_list[-1].args[0])

    async def test_second_extracted_file_send_failure_refunds(self):
        callback, bot, fsm = fake_callback("zip:extract")
        callback.message.answer_document.side_effect = [
            None, OSError("Telegram unreachable")
        ]

        def extract(source, folder):
            files = []
            for name in ("01_first.txt", "02_second.txt"):
                p = folder / name
                p.write_text("content", encoding="utf-8")
                files.append((p, name))
            return files

        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         return_value=OPERATION),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "archive_module") as archive,
            patch.object(main.logger, "exception"),
        ):
            archive.extract.side_effect = extract
            await main.run_action(callback, bot, fsm)
            settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)
        self.assertEqual(callback.message.answer_document.await_count, 2)
        self.assertIn("Не удалось обработать файл",
                      callback.message.answer.await_args_list[-1].args[0])

    async def test_bundle_create_or_telegram_delivery_failure_refunds(self):
        for fails_on in ("create", "delivery"):
            with self.subTest(fails_on=fails_on):
                message, bot, fsm, _ = zip_bundle()

                def create(inputs, target):
                    if fails_on == "create":
                        raise ValueError("ZIP rejected")
                    target.write_bytes(b"mock ZIP")
                    return len(inputs)

                if fails_on == "delivery":
                    message.answer_document.side_effect = OSError("send failed")
                with (
                    patch.object(main, "allow_processing", new_callable=AsyncMock,
                                 return_value=True),
                    patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                                 return_value=OPERATION),
                    patch.object(main, "settle_bot_operation",
                                 new_callable=AsyncMock) as settle,
                    patch.object(main, "archive_module") as archive,
                    patch.object(main.logger, "exception"),
                ):
                    archive.create.side_effect = create
                    await main.run_zip_bundle(message, bot, fsm, USER)
                    archive.create.assert_called_once()
                    settle.assert_awaited_once_with(USER, TOKEN, OPERATION, False)
                if fails_on == "create":
                    message.answer_document.assert_not_awaited()
                    self.assertIn("ZIP rejected", message.answer.await_args_list[-1].args[0])
                else:
                    message.answer_document.assert_awaited_once()
                    self.assertIn("Не удалось собрать ZIP",
                                  message.answer.await_args_list[-1].args[0])
                fsm.clear.assert_awaited_once()

    async def test_bundling_in_other_chat_rejected_before_quota_or_download(self):
        message, bot, fsm, _ = zip_bundle(chat_id=USER + 1)
        with (
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
            patch.object(main, "check_processing_access",
                         new_callable=AsyncMock) as access,
            patch.object(main, "archive_module") as archive,
        ):
            await main.run_zip_bundle(message, bot, fsm, USER)
            access.assert_not_awaited()
            reserve.assert_not_awaited()
            archive.create.assert_not_called()
        bot.download.assert_not_awaited()
        fsm.clear.assert_not_awaited()

    async def test_inactive_or_incomplete_bundle_does_not_run(self):
        for state, count in (("other:state", 2), (None, 1)):
            with self.subTest(state=state, count=count):
                message, bot, fsm, _ = zip_bundle(count=count, state=state)
                if state is None:
                    fsm.get_state.return_value = main.ZipState.collecting.state
                with (
                    patch.object(main, "allow_processing", new_callable=AsyncMock) as access,
                    patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
                    patch.object(main, "archive_module") as archive,
                ):
                    await main.run_zip_bundle(message, bot, fsm, USER)
                    access.assert_not_awaited()
                    reserve.assert_not_awaited()
                    archive.create.assert_not_called()
                bot.download.assert_not_awaited()
                fsm.clear.assert_not_awaited()

    async def test_foreign_invalid_busy_and_oversized_callbacks_do_not_process(self):
        cases = (
            fake_callback("zip:list", owner=USER + 1),
            fake_callback("zip:extract", chat_id=USER + 1),
            fake_callback("zip:wrong"),
            fake_callback("zip:extract", filename="not-a-zip.txt"),
            fake_callback("zip:list", size=main.MAX_BYTES + 1),
            fake_callback("zip:extract", size=None),
            fake_callback("zip:extract", busy=main.ZipState.collecting.state),
        )
        for callback, bot, fsm in cases:
            with (
                self.subTest(action=callback.data, chat=callback.message.chat.id),
                patch.object(main, "Message", SimpleNamespace),
                patch.object(main, "allow_processing", new_callable=AsyncMock) as allow,
                patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
                patch.object(main, "archive_module") as archive,
            ):
                await main.run_action(callback, bot, fsm)
                allow.assert_not_awaited()
                reserve.assert_not_awaited()
                bot.download.assert_not_awaited()
                archive.inspect.assert_not_called()
                archive.extract.assert_not_called()
                archive.create.assert_not_called()

    async def test_entitlement_denial_precedes_worker_and_reservation(self):
        callback, bot, fsm = fake_callback("zip:list")
        with (
            patch.object(main, "Message", SimpleNamespace),
            patch.object(main, "allow_processing", new_callable=AsyncMock,
                         return_value=False) as allow,
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
            patch.object(main, "archive_module") as archive,
        ):
            await main.run_action(callback, bot, fsm)
            allow.assert_awaited_once()
            reserve.assert_not_awaited()
            bot.download.assert_not_awaited()
            archive.inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
