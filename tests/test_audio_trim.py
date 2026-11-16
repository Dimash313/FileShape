"""Telegram-only audio trim: strict range validation, FFmpeg and FSM regressions."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import shutil
import tempfile
import unittest
import wave

from services.audio_trim import parse_trim_range, trim_audio


class AudioTrimRangeTests(unittest.TestCase):
    def test_valid_ranges_and_utc_independent_integer_seconds(self):
        cases = {
            "00:00:00-00:00:01": (0, 1),
            "00:00:05-00:00:20": (5, 20),
            "00:01:03 - 00:02:34": (63, 154),
            "00:09:59-00:10:00": (599, 600),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_trim_range(value), expected)

    def test_reject_malformed_outside_range_or_injection(self):
        invalid = (
            None, "", " ", "00:00:10", "0:00:01-00:00:02",
            "-00:00:01-00:00:02", "00:00:00--00:00:01",
            "00:00:03-00:00:03", "00:00:05-00:00:04",
            "00:00:59-00:00:60", "00:60:00-00:60:01",
            "01:00:00-01:00:01", "00:00:00-00:10:01",
            "00:00:00-00:00:00", "00:00:00;rm -rf /",
            "00:00:00-00:00:02\n-next", " 00:00:00-00:00:02 \n -y",
            "00:00:00-00:00:02" * 100,
        )
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                parse_trim_range(value)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioTrimFFmpegTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.wav"
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * (16000 * 5))

    def test_trim_real_pcm_and_verify_mp3_duration(self):
        from services.audio_tools import probe_audio
        target = self.root / "trimmed.mp3"
        details = trim_audio(self.source, target, "00:00:01-00:00:03")
        self.assertEqual(details["start_seconds"], 1)
        self.assertEqual(details["end_seconds"], 3)
        self.assertEqual(details["output_format"], "mp3")
        self.assertTrue(target.is_file())
        self.assertGreater(target.stat().st_size, 100)
        self.assertAlmostEqual(probe_audio(target)["seconds"], 2.0, delta=0.25)
        self.assertAlmostEqual(probe_audio(self.source)["seconds"], 5.0, delta=0.1)

    def test_reject_end_past_actual_duration_without_partial_result(self):
        target = self.root / "trimmed.mp3"
        with self.assertRaises(ValueError):
            trim_audio(self.source, target, "00:00:00-00:00:06")
        self.assertFalse(target.exists())

    def test_reject_mislabeled_bytes_and_unsupported_output(self):
        bad = self.root / "bad.mp3"
        bad.write_bytes(b"not audio")
        with self.assertRaises(ValueError):
            trim_audio(bad, self.root / "out.mp3", "00:00:00-00:00:01")
        with self.assertRaises(ValueError):
            trim_audio(self.source, self.root / "notmp3.wav", "00:00:01-00:00:03")

    def test_reject_symlink_input(self):
        link = self.root / "link.wav"
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            trim_audio(link, self.root / "out.mp3", "00:00:01-00:00:03")


@asynccontextmanager
async def fake_meter(*_args, **_kwargs):
    yield


class AudioTrimBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_range_does_not_reserve_quota_or_download(self):
        from main import audio_trim_range
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            from_user=SimpleNamespace(id=111),
            text="00:00:05-00:00:04",
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": 111, "file_id": "opaque-id", "suffix": ".wav",
            }),
            clear=AsyncMock(),
        )
        bot = SimpleNamespace(token="testing", download=AsyncMock())
        with patch("main.allow_processing", new_callable=AsyncMock) as gate:
            await audio_trim_range(message, bot, state)
        gate.assert_not_awaited()
        bot.download.assert_not_awaited()
        self.assertIn("Начало", message.answer.call_args.args[0])
        state.clear.assert_not_awaited()

    async def test_private_owner_binding_blocks_foreign_state(self):
        from main import audio_trim_range
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            from_user=SimpleNamespace(id=111),
            text="00:00:01-00:00:02",
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": 222, "file_id": "foreign", "suffix": ".wav",
            }),
            clear=AsyncMock(),
        )
        bot = SimpleNamespace(token="testing", download=AsyncMock())
        with patch("main.allow_processing", new_callable=AsyncMock) as gate:
            await audio_trim_range(message, bot, state)
        gate.assert_not_awaited()
        bot.download.assert_not_awaited()
        state.clear.assert_awaited_once()

    async def test_range_submission_delivers_one_metered_result_and_clears_fsm(self):
        from main import audio_trim_range, file_menu
        self.assertIn("audio:trim", [
            b.callback_data for row in file_menu("audio").inline_keyboard for b in row
        ])
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            from_user=SimpleNamespace(id=111),
            text="00:00:01-00:00:03",
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": 111, "file_id": "opaque-id", "suffix": ".wav",
            }),
            clear=AsyncMock(),
        )
        async def download(_file_id, destination):
            Path(destination).write_bytes(b"internal input bytes")
        bot = SimpleNamespace(token="testing", download=AsyncMock(side_effect=download))
        def fake_trim(_source, target, spec):
            self.assertEqual(spec, "00:00:01-00:00:03")
            target.write_bytes(b"output bytes")
            return {"start_seconds": 1, "end_seconds": 3}
        with (
            patch("main.allow_processing", new_callable=AsyncMock, return_value=True),
            patch("main.metered_bot_work", side_effect=fake_meter) as meter,
            patch("main.trim_audio", side_effect=fake_trim) as trimmed,
            patch("main.send_result", new_callable=AsyncMock) as send,
            patch("main.remove_status", new_callable=AsyncMock),
        ):
            await audio_trim_range(message, bot, state)
        self.assertEqual(meter.call_count, 1)
        self.assertEqual(trimmed.call_count, 1)
        send.assert_awaited_once()
        state.clear.assert_awaited_once()
        bot.download.assert_awaited_once()

    async def test_quota_unavailable_never_downloads_file(self):
        from main import audio_trim_range
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            from_user=SimpleNamespace(id=111),
            text="00:00:01-00:00:03",
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": 111, "file_id": "opaque-id", "suffix": ".wav",
            }),
            clear=AsyncMock(),
        )
        bot = SimpleNamespace(token="testing", download=AsyncMock())
        with patch("main.allow_processing", new_callable=AsyncMock, return_value=False):
            await audio_trim_range(message, bot, state)
        bot.download.assert_not_awaited()
        state.clear.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
