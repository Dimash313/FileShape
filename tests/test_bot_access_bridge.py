"""Gate all Telegram bot conversion paths without opening API metadata SQLite."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Document, Message, User

import main
from api.internal_access import ReplayGuard
from services.bot_access import check_processing_access


TOKEN = "123456:TEST"


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


class _Response:
    def __init__(self, code=200, value=None):
        self.status = code
        self.value = value if value is not None else {"decision": "allowed"}

    async def json(self, **kwargs):
        return self.value


class _Session:
    def __init__(self, response):
        self.response = response
        self.url = None
        self.headers = None
        self.redirects = None

    def post(self, url, *, headers, allow_redirects):
        self.url, self.headers, self.redirects = url, headers, allow_redirects
        return _AsyncContext(self.response)


class BotAccessBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_signed_request_never_sends_token(self):
        session = _Session(_Response())
        with patch("services.bot_access.aiohttp.ClientSession", return_value=_AsyncContext(session)):
            decision = await check_processing_access(
                11, TOKEN, url="http://api:8000/internal/v1/access/check"
            )
        self.assertEqual(decision, "allowed")
        self.assertFalse(session.redirects)
        self.assertNotIn(TOKEN, str(session.headers))
        ReplayGuard().verify(
            token=TOKEN,
            user=session.headers["X-FileShape-User"],
            timestamp=session.headers["X-FileShape-Time"],
            nonce=session.headers["X-FileShape-Nonce"],
            signature=session.headers["X-FileShape-Signature"],
            now=int(session.headers["X-FileShape-Time"]),
        )

    async def test_api_rejection_and_unknown_decision_fail_closed(self):
        for response, expected in [
            (_Response(503), "verification_unavailable"),
            (_Response(302), "verification_unavailable"),
            (_Response(200, {"decision": "other"}), "verification_unavailable"),
            (_Response(200, {"decision": "subscription_required"}), "subscription_required"),
        ]:
            with self.subTest(expected=expected), patch(
                "services.bot_access.aiohttp.ClientSession",
                return_value=_AsyncContext(_Session(response)),
            ):
                result = await check_processing_access(
                    11, TOKEN, url="http://api:8000/internal/v1/access/check"
                )
                self.assertEqual(result, expected)

    async def test_malformed_url_and_identity_fail_closed(self):
        for url in ("https://evil.example/", "file:///etc/passwd",
                    "http://bad:pass@api/internal/v1/access/check",
                    "http://api/internal/v1/access/check?x=1"):
            with self.subTest(url=url):
                self.assertEqual(await check_processing_access(11, TOKEN, url=url),
                                 "verification_unavailable")
        self.assertEqual(await check_processing_access(0, TOKEN),
                         "verification_unavailable")

    async def test_standalone_mode_is_explicitly_ungated(self):
        with patch.dict("os.environ", {"FILESHAPE_ACCESS_GATE_URL": ""}):
            self.assertEqual(await check_processing_access(11, TOKEN), "allowed")


class BotEntryPointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor = User(id=11, is_bot=False, first_name="Owner")
        self.bot_user = User(id=99, is_bot=True, first_name="FileShape")
        self.chat = Chat(id=11, type="private")
        self.bot = SimpleNamespace(token=TOKEN, download=AsyncMock())

    def make_message(self, message_id, *, sender=None, reply=None, doc=None, text=None):
        return Message(
            message_id=message_id,
            date=datetime.now(timezone.utc),
            chat=self.chat,
            from_user=sender or self.actor,
            reply_to_message=reply,
            document=doc,
            text=text,
        )

    async def test_denied_access_and_foreign_chat(self):
        message = SimpleNamespace(chat=SimpleNamespace(type="private", id=11),
                                  answer=AsyncMock())
        with patch.object(main, "check_processing_access", new_callable=AsyncMock,
                          return_value="subscription_required") as call:
            self.assertFalse(await main.allow_processing(message, self.bot, 11))
            call.assert_awaited_once_with(11, TOKEN)
            self.assertIn("подписка", message.answer.call_args.args[0])
        with patch.object(main, "check_processing_access", new_callable=AsyncMock) as call:
            self.assertFalse(await main.allow_processing(message, self.bot, 12))
            call.assert_not_awaited()

    async def test_action_callback_denial_before_state_or_download(self):
        doc = Document(file_id="file", file_unique_id="unique",
                       file_name="file.pdf", file_size=200)
        origin = self.make_message(1, doc=doc)
        menu = self.make_message(2, sender=self.bot_user, reply=origin)
        state = SimpleNamespace(get_state=AsyncMock(return_value=None),
                                set_state=AsyncMock(), update_data=AsyncMock())
        for action in ("pdf:rotate", "pdf:merge", "zip:create"):
            callback = SimpleNamespace(message=menu, from_user=self.actor,
                                       data=action, answer=AsyncMock())
            with self.subTest(action=action), patch.object(
                main, "allow_processing", new_callable=AsyncMock, return_value=False
            ) as gate:
                await main.run_action(callback, self.bot, state)
                gate.assert_awaited_once_with(menu, self.bot, 11)
                state.set_state.assert_not_awaited()
                self.bot.download.assert_not_awaited()

    async def test_merge_and_zip_completion_denied_before_download(self):
        for operation, state_value, data in (
            (main.run_merge, main.MergeState.collecting.state,
             {"pdfs": [{"file_id": "a"}, {"file_id": "b"}]}),
            (main.run_zip_bundle, main.ZipState.collecting.state,
             {"zip_files": [{"file_id": "a"}, {"file_id": "b"}]}),
        ):
            state = SimpleNamespace(
                get_state=AsyncMock(return_value=state_value),
                get_data=AsyncMock(return_value=data), clear=AsyncMock()
            )
            msg = SimpleNamespace(answer=AsyncMock())
            with self.subTest(op=operation.__name__), patch.object(
                main, "allow_processing", new_callable=AsyncMock, return_value=False
            ) as gate:
                await operation(msg, self.bot, state, 11)
                gate.assert_awaited_once_with(msg, self.bot, 11)
                state.clear.assert_not_awaited()
                self.bot.download.assert_not_awaited()

    async def test_pdf_page_operation_denied_before_download(self):
        msg = self.make_message(3, text="1-3")
        state = SimpleNamespace(get_data=AsyncMock(return_value={
            "file_id": "file", "pdf_mode": "pdf:extract"
        }), clear=AsyncMock())
        with patch.object(main, "allow_processing", new_callable=AsyncMock,
                          return_value=False) as gate:
            await main.extract_by_range(msg, self.bot, state)
            gate.assert_awaited_once_with(msg, self.bot, 11)
            self.bot.download.assert_not_awaited()
            state.clear.assert_not_awaited()

    async def test_quota_denial_blocks_merge_zip_and_page_processing_before_download(self):
        for operation, state_value, data in (
            (main.run_merge, main.MergeState.collecting.state,
             {"pdfs": [{"file_id": "a"}, {"file_id": "b"}]}),
            (main.run_zip_bundle, main.ZipState.collecting.state,
             {"zip_files": [{"file_id": "a"}, {"file_id": "b"}]}),
        ):
            state = SimpleNamespace(
                get_state=AsyncMock(return_value=state_value),
                get_data=AsyncMock(return_value=data), clear=AsyncMock()
            )
            msg = SimpleNamespace(
                answer=AsyncMock(),
                chat=SimpleNamespace(type="private", id=11),
            )
            with (
                self.subTest(handler=operation.__name__),
                patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True),
                patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                             side_effect=main.BotOperationQuotaExceeded()),
            ):
                await operation(msg, self.bot, state, 11)
                self.bot.download.assert_not_awaited()
                state.clear.assert_not_awaited()

        state = SimpleNamespace(
            get_data=AsyncMock(return_value={"file_id": "file", "pdf_mode": "pdf:extract"}),
            clear=AsyncMock(),
        )
        msg = SimpleNamespace(
            text="1-2", from_user=self.actor,
            chat=SimpleNamespace(type="private", id=11),
            answer=AsyncMock(),
        )
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         side_effect=main.BotOperationQuotaExceeded()),
        ):
            await main.extract_by_range(msg, self.bot, state)
            self.bot.download.assert_not_awaited()
            state.clear.assert_not_awaited()

    async def test_quota_denial_blocks_single_file_worker_before_download(self):
        doc = Document(file_id="file", file_unique_id="unique", file_name="file.pdf", file_size=200)
        origin = self.make_message(1, doc=doc)
        menu = self.make_message(2, sender=self.bot_user, reply=origin)
        state = SimpleNamespace(get_state=AsyncMock(return_value=None))
        callback = SimpleNamespace(message=menu, from_user=self.actor, data="pdf:rotate", answer=AsyncMock())
        with (
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock,
                         side_effect=main.BotOperationQuotaExceeded()),
            patch.object(Message, "answer", new_callable=AsyncMock),
        ):
            await main.run_action(callback, self.bot, state)
        self.bot.download.assert_not_awaited()

    async def test_callback_completion_uses_actor_not_bot_message_sender(self):
        msg = self.make_message(2, sender=self.bot_user)
        for method, handler in ((main.run_merge, main.done_button),
                                (main.run_zip_bundle, main.done_zip_button)):
            cb = SimpleNamespace(message=msg, from_user=self.actor,
                                 answer=AsyncMock())
            state = SimpleNamespace()
            with patch.object(main, method.__name__, new_callable=AsyncMock) as call:
                await handler(cb, self.bot, state)
                call.assert_awaited_once_with(msg, self.bot, state, 11)


if __name__ == "__main__":
    unittest.main()
