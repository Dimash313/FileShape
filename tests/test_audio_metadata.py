"""MP3 metadata parser, stream-copy, artwork and Telegram owner/quota regressions."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import shutil
import subprocess
import tempfile
import unittest
import wave

from services.audio_metadata import edit_mp3_tags, parse_tag_edits, _inspect


class MP3TagParserTests(unittest.TestCase):
    def test_five_fields_keep_and_clear(self):
        self.assertEqual(
            parse_tag_edits("Урок | Чтец | Сборник | 2026 | Речь"),
            {"title": "Урок", "artist": "Чтец", "album": "Сборник",
             "date": "2026", "genre": "Речь"},
        )
        self.assertEqual(parse_tag_edits("- | ~ | - | - | -"), {"artist": ""})

    def test_reject_empty_noop_controls_wrong_year_and_injection(self):
        for value in (
            None, "", "Title", " | | | | ", "- | - | - | - | -",
            "T | P | A | next | G", "T | P | A | ２０２６ | G",
            "T | P | A | 2026 | G | extra",
            "Name\n-next | Person | Album | 2026 | Genre",
            "X\x00Y | Person | Album | 2026 | Genre",
            ("x" * 121) + " | P | A | 2026 | G",
            "a | b | c | 2026 | " + "d" * 1000,
        ):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                parse_tag_edits(value)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MP3TagStreamCopyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.wav = self.folder / "silent.wav"
        self.mp3 = self.folder / "original.mp3"
        with wave.open(str(self.wav), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * 16000)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(self.wav),
             "-c:a", "libmp3lame", str(self.mp3)],
            capture_output=True, check=True,
        )

    def test_edit_tags_and_clear_artist_without_reencoding(self):
        first = self.folder / "tags.mp3"
        original = _inspect(self.mp3)
        tags = edit_mp3_tags(
            self.mp3, first, parse_tag_edits("Урок | Чтец | Альбом | 2026 | Речь"),
        )
        self.assertEqual(tags["title"], "Урок")
        self.assertEqual(tags["artist"], "Чтец")
        self.assertEqual(tags["date"], "2026")
        self.assertEqual(_inspect(first)["audio_codec"], original["audio_codec"])
        second = self.folder / "cleared.mp3"
        cleared = edit_mp3_tags(
            first, second, parse_tag_edits("- | ~ | - | - | -"),
        )
        self.assertEqual(cleared["title"], "Урок")
        self.assertNotIn("artist", cleared)
        self.assertEqual(cleared["date"], "2026")

    def test_existing_cover_survives_metadata_edit(self):
        # A solid geometric test image, not a marketing asset or depiction.
        from PIL import Image
        image = self.folder / "abstract.png"
        Image.new("RGB", (16, 16), (40, 80, 120)).save(image)
        with_cover = self.folder / "cover.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(self.mp3), "-i", str(image),
             "-map", "0:a", "-map", "1:v", "-c", "copy",
             "-disposition:v:0", "attached_pic", str(with_cover)],
            capture_output=True, check=True,
        )
        self.assertIsNotNone(_inspect(with_cover)["cover_index"])
        target = self.folder / "cover_edited.mp3"
        updated = edit_mp3_tags(
            with_cover, target, parse_tag_edits("Запись | - | - | - | -"),
        )
        self.assertEqual(updated["title"], "Запись")
        self.assertIsNotNone(_inspect(target)["cover_index"])

    def test_reject_malformed_mp3_symlink_wrong_output_and_existing_result(self):
        bad = self.folder / "bad.mp3"
        bad.write_bytes(b"this is not MP3")
        with self.assertRaises(ValueError):
            edit_mp3_tags(bad, self.folder / "broken.mp3", {"title": "Test"})
        self.assertFalse((self.folder / "broken.mp3").exists())
        link = self.folder / "link.mp3"
        link.symlink_to(self.mp3)
        with self.assertRaises(ValueError):
            edit_mp3_tags(link, self.folder / "other.mp3", {"title": "X"})
        with self.assertRaises(ValueError):
            edit_mp3_tags(self.mp3, self.folder / "output.wav", {"title": "X"})
        with self.assertRaises(ValueError):
            edit_mp3_tags(self.mp3, self.mp3, {"title": "X"})
        with self.assertRaises(ValueError):
            edit_mp3_tags(self.mp3, self.folder / "other.mp3", {"unsafe": "X"})
        occupied = self.folder / "existing.mp3"
        occupied.write_bytes(b"existing result must not be overwritten")
        with self.assertRaises(ValueError):
            edit_mp3_tags(self.mp3, occupied, {"title": "X"})
        self.assertEqual(occupied.read_bytes(), b"existing result must not be overwritten")

    def test_failed_subprocess_output_is_cleaned_up(self):
        original = subprocess.run
        target = self.folder / "partial.mp3"

        def fail_ffmpeg(args, *pargs, **kwargs):
            if Path(args[0]).name == "ffmpeg":
                target.write_bytes(b"partial output")
                return subprocess.CompletedProcess(args, 1, b"", b"error")
            return original(args, *pargs, **kwargs)

        with patch("services.audio_metadata.subprocess.run", side_effect=fail_ffmpeg):
            with self.assertRaises(ValueError):
                edit_mp3_tags(self.mp3, target, {"title": "Test"})
        self.assertFalse(target.exists())


@asynccontextmanager
async def fake_meter(*_args, **_kwargs):
    yield


class MP3TagBotTests(unittest.IsolatedAsyncioTestCase):
    def make(self, *, owner=111, text="Урок"):
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            from_user=SimpleNamespace(id=111),
            text=text,
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": owner, "file_id": "opaque-telegram-file", "suffix": ".mp3",
                "tag_field": "title",
            }),
            clear=AsyncMock(),
        )
        bot = SimpleNamespace(token="test-only", download=AsyncMock())
        return message, state, bot

    async def test_tag_button_only_for_mp3(self):
        from main import file_menu
        def ids(kind, suffix):
            return [b.callback_data for row in file_menu(kind, suffix).inline_keyboard for b in row]
        self.assertIn("audio:tags", ids("audio", ".mp3"))
        self.assertNotIn("audio:tags", ids("audio", ".wav"))
        self.assertNotIn("audio:tags", ids("audio", ".ogg"))
        self.assertIn("audio:trim", ids("audio", ".wav"))

    async def test_field_selection_menu_and_cover_not_yet_active(self):
        from main import tag_editor_keyboard, choose_audio_tag, TagState
        menu = [button.callback_data for row in tag_editor_keyboard().inline_keyboard
                for button in row]
        self.assertEqual(set(menu), {
            "tags:title", "tags:artist", "tags:album", "tags:date",
            "tags:genre", "tags:cover", "tags:cancel",
        })
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=111),
            answer=AsyncMock(),
        )
        state = SimpleNamespace(
            get_data=AsyncMock(return_value={
                "owner_id": 111, "file_id": "opaque", "suffix": ".mp3",
            }),
            get_state=AsyncMock(return_value=TagState.choosing_field.state),
            set_state=AsyncMock(),
            update_data=AsyncMock(),
            clear=AsyncMock(),
        )
        callback = SimpleNamespace(
            message=message, from_user=SimpleNamespace(id=111),
            data="tags:artist", answer=AsyncMock(),
        )
        await choose_audio_tag(callback, state)
        state.update_data.assert_awaited_once_with(tag_field="artist")
        state.set_state.assert_awaited_once_with(TagState.waiting_for_fields)
        message.answer.assert_awaited_once()
        callback.data = "tags:cover"
        state.update_data.reset_mock()
        await choose_audio_tag(callback, state)
        state.update_data.assert_not_awaited()

    async def test_wrong_owner_cannot_download_or_use_quota(self):
        from main import audio_tag_fields
        message, state, bot = self.make(owner=222)
        with patch("main.allow_processing", new_callable=AsyncMock) as access:
            await audio_tag_fields(message, bot, state)
        access.assert_not_awaited()
        bot.download.assert_not_awaited()
        state.clear.assert_awaited_once()

    async def test_invalid_metadata_rejected_before_reservation(self):
        from main import audio_tag_fields
        message, state, bot = self.make(text="Name\n-y")
        with patch("main.allow_processing", new_callable=AsyncMock) as access:
            await audio_tag_fields(message, bot, state)
        access.assert_not_awaited()
        bot.download.assert_not_awaited()
        state.clear.assert_not_awaited()

    async def test_edit_download_and_send_as_one_metered_operation(self):
        from main import audio_tag_fields
        message, state, bot = self.make()
        async def fake_download(_file_id, destination):
            Path(destination).write_bytes(b"opaque downloaded content")
        bot.download.side_effect = fake_download
        def fake_edit(_source, target, edits):
            self.assertEqual(edits, {"title": "Урок"})
            target.write_bytes(b"edited mp3 for mocked bot delivery")
            return {"title": "Урок"}
        with (
            patch("main.allow_processing", new_callable=AsyncMock, return_value=True),
            patch("main.metered_bot_work", side_effect=fake_meter) as meter,
            patch("main.edit_mp3_tags", side_effect=fake_edit) as edit,
            patch("main.send_result", new_callable=AsyncMock) as send,
            patch("main.remove_status", new_callable=AsyncMock),
        ):
            await audio_tag_fields(message, bot, state)
        self.assertEqual(meter.call_count, 1)
        self.assertEqual(edit.call_count, 1)
        send.assert_awaited_once()
        bot.download.assert_awaited_once()
        state.clear.assert_awaited_once()

    async def test_failed_access_never_downloads_file(self):
        from main import audio_tag_fields
        message, state, bot = self.make()
        with patch("main.allow_processing", new_callable=AsyncMock, return_value=False):
            await audio_tag_fields(message, bot, state)
        bot.download.assert_not_awaited()
        state.clear.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
