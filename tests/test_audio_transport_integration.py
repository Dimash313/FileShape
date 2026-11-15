"""Audio transport regression checks using generated digital silence only.

Exercises the real existing audio converter behind HTTP and Telegram
dispatch, without contacting external services or bundling media assets.
"""
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import wave

from aiogram.types import Audio, Chat, Message, User
from fastapi.testclient import TestClient

import main
from api import server
from api.admission import AdmissionQueue
from api.jobs import JobRegistry
from services.audio_tools import probe_audio
from test_api import TOKEN, signed_init_data


OWNER = 12345
BOT_TOKEN = "123456:TEST-TRANSPORT"
LEASE_ID = "B" * 32


def silent_wav_bytes() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000)
    return buffer.getvalue()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioHttpIntegrationTests(unittest.TestCase):
    """Existing signed API route, not a mocked authorization dependency."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "BOT_TOKEN": TOKEN,
            "FILESHAPE_STATE_DIR": str(Path(self.temp.name) / "state"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        admission = patch.object(server, "admission", AdmissionQueue())
        admission.start()
        self.addCleanup(admission.stop)
        registry = patch.object(server, "jobs", JobRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        limiter = patch.object(server, "RATE_LIMIT_PER_MINUTE", 1000)
        limiter.start()
        self.addCleanup(limiter.stop)
        self.client = TestClient(server.api)
        self.addCleanup(self.client.close)
        self.headers = {"X-Telegram-Init-Data": signed_init_data(OWNER)}
        self.wav = silent_wav_bytes()
        self.created_workspaces = []
        actual_workspace = server.Workspace

        def track_workspace(*args, **kwargs):
            work = actual_workspace(*args, **kwargs)
            self.created_workspaces.append(Path(work.name))
            return work

        tracker = patch.object(server, "Workspace", side_effect=track_workspace)
        tracker.start()
        self.addCleanup(tracker.stop)

    def post(self, *, headers=None, action="audio:mp3", contents=None):
        return self.client.post(
            "/api/v1/convert", headers=self.headers if headers is None else headers,
            data={"action": action},
            files={"upload": (
                "recording.wav", self.wav if contents is None else contents, "audio/wav"
            )},
        )

    def assert_workspaces_gone(self):
        for path in self.created_workspaces:
            self.assertFalse(path.exists(), f"Leaked workspace: {path}")

    def test_signed_api_real_mp3_response_and_workspace_lifecycle(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("attachment", response.headers.get("content-disposition", ""))
        self.assertEqual(response.content[:3], b"ID3")
        self.assertTrue(response.headers.get("x-fileshape-job-id"))
        self.assertEqual(len(self.created_workspaces), 1)
        self.assert_workspaces_gone()

        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "received.mp3"
            media.write_bytes(response.content)
            self.assertEqual(probe_audio(media)["codec"], "mp3")

    def test_missing_or_tampered_telegram_auth_rejected_before_workspace(self):
        for headers in ({}, {"X-Telegram-Init-Data": "bad-signature"}):
            with self.subTest(headers=headers):
                response = self.post(headers=headers)
                self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.created_workspaces, [])

    def test_invalid_audio_is_422_and_deletes_workspace(self):
        response = self.post(contents=b"RIFF" + b"not a real WAV")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(self.created_workspaces), 1)
        self.assert_workspaces_gone()

    def test_unexposed_multi_input_and_video_actions_rejected(self):
        for action in ("audio:join", "video:audio", "audio:extract"):
            with self.subTest(action=action):
                response = self.post(action=action)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.created_workspaces, [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioTelegramIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Actual handler + FFmpeg, stubbed Telegram network and ledger IO."""

    def setUp(self):
        self.wav = silent_wav_bytes()
        self.paths = []
        self.bot = SimpleNamespace(token=BOT_TOKEN, download=AsyncMock(side_effect=self.download))
        self.state = SimpleNamespace(get_state=AsyncMock(return_value=None))
        self.sent = []

    async def download(self, _file, *, destination):
        self.paths.append(Path(destination))
        Path(destination).write_bytes(self.wav)

    def callback(self, *, owner=OWNER, actor=OWNER, chat_id=None, action="audio:mp3"):
        chat = Chat(id=actor if chat_id is None else chat_id, type="private")
        original_user = User(id=owner, is_bot=False, first_name="User")
        bot_user = User(id=999, is_bot=True, first_name="FileShape")
        now = datetime.now(timezone.utc)
        origin = Message(
            message_id=1, date=now, chat=chat, from_user=original_user,
            audio=Audio(
                file_id="opaque-id", file_unique_id="opaque-unique",
                duration=1, file_size=len(self.wav), file_name="silence.wav",
            ),
        )
        menu = Message(
            message_id=2, date=now, chat=chat, from_user=bot_user,
            text="FileShape", reply_to_message=origin,
        )
        return SimpleNamespace(
            message=menu, from_user=SimpleNamespace(id=actor),
            data=action, answer=AsyncMock(),
        )

    async def receive(self, _message, path, *_args):
        self.assertTrue(Path(path).is_file())
        self.assertEqual(probe_audio(Path(path))["codec"], "mp3")
        self.sent.append(bytes(Path(path).read_bytes()))
        self.paths.append(Path(path))

    def assert_workspaces_gone(self):
        for path in self.paths:
            self.assertFalse(path.parent.exists(), f"Leaked Telegram folder: {path.parent}")

    async def test_real_bot_convert_success_settles_quota_after_delivery(self):
        cb = self.callback()
        async def deliver(*args, **kwargs):
            await self.receive(*args, **kwargs)
        with (
            patch.object(Message, "answer", new_callable=AsyncMock),
            patch.object(main, "remove_status", new_callable=AsyncMock),
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True) as access,
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=LEASE_ID) as reserve,
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "send_result", new_callable=AsyncMock, side_effect=deliver) as send,
        ):
            await main.run_action(cb, self.bot, self.state)
        access.assert_awaited_once()
        reserve.assert_awaited_once_with(OWNER, BOT_TOKEN)
        settle.assert_awaited_once_with(OWNER, BOT_TOKEN, LEASE_ID, True)
        send.assert_awaited_once()
        self.bot.download.assert_awaited_once()
        self.assertEqual(len(self.sent), 1)
        self.assert_workspaces_gone()

    async def test_foreign_owner_button_is_denied_before_quota_or_download(self):
        cb = self.callback(owner=OWNER + 1)
        with (
            patch.object(Message, "answer", new_callable=AsyncMock),
            patch.object(main, "allow_processing", new_callable=AsyncMock) as access,
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
        ):
            await main.run_action(cb, self.bot, self.state)
        self.assertEqual(cb.answer.await_count, 1)
        access.assert_not_awaited()
        reserve.assert_not_awaited()
        self.bot.download.assert_not_awaited()

    async def test_access_denied_never_downloads_or_reserves(self):
        cb = self.callback()
        with (
            patch.object(Message, "answer", new_callable=AsyncMock),
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=False),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock) as reserve,
        ):
            await main.run_action(cb, self.bot, self.state)
        reserve.assert_not_awaited()
        self.bot.download.assert_not_awaited()

    async def test_download_failure_releases_lease_and_temp_folder(self):
        cb = self.callback()
        self.bot.download.side_effect = OSError("download transport failed")
        with (
            patch.object(Message, "answer", new_callable=AsyncMock),
            patch.object(main, "remove_status", new_callable=AsyncMock),
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=LEASE_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "send_result", new_callable=AsyncMock) as send,
        ):
            await main.run_action(cb, self.bot, self.state)
        settle.assert_awaited_once_with(OWNER, BOT_TOKEN, LEASE_ID, False)
        send.assert_not_awaited()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.paths, [])

    async def test_telegram_send_failure_releases_lease_and_removes_result(self):
        cb = self.callback()
        async def fail_delivery(_message, path, *_args):
            self.paths.append(Path(path))
            self.assertTrue(Path(path).is_file())
            raise OSError("Telegram network failure")
        with (
            patch.object(Message, "answer", new_callable=AsyncMock),
            patch.object(main, "remove_status", new_callable=AsyncMock),
            patch.object(main, "allow_processing", new_callable=AsyncMock, return_value=True),
            patch.object(main, "reserve_bot_operation", new_callable=AsyncMock, return_value=LEASE_ID),
            patch.object(main, "settle_bot_operation", new_callable=AsyncMock) as settle,
            patch.object(main, "send_result", new_callable=AsyncMock, side_effect=fail_delivery),
        ):
            await main.run_action(cb, self.bot, self.state)
        settle.assert_awaited_once_with(OWNER, BOT_TOKEN, LEASE_ID, False)
        self.assert_workspaces_gone()


if __name__ == "__main__":
    unittest.main()
