"""Safety regressions for Telegram audio trimming, with generated silence only."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.audio_tools import _probe_pinned_audio, probe_audio
from services.audio_trim import MAX_AUDIO_INPUT_BYTES, trim_audio


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required"
)
class TrimPinnedSourceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "five_seconds.wav"
        self.target = self.root / "trimmed.mp3"
        with wave.open(str(self.source), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * (16000 * 5))

    def test_real_trim_private_output_and_no_scratch(self):
        result = trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertEqual(result["start_seconds"], 1)
        self.assertEqual(result["end_seconds"], 3)
        self.assertEqual(result["output_format"], "mp3")
        self.assertAlmostEqual(probe_audio(self.target)["seconds"], 2.0, delta=0.25)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_renamed_source_between_probe_and_ffmpeg_preserves_original(self):
        safe_inode = self.source.stat().st_ino
        backup = self.root / "original.wav"
        inspected = []
        real_probe = _probe_pinned_audio
        real_run = subprocess.run

        def swap_after_probe(pinned_path, fd, *, exact):
            details = real_probe(pinned_path, fd, exact=exact)
            self.source.rename(backup)
            self.source.write_text("ffconcat version 1.0\nfile original.wav\n")
            inspected.append((pinned_path, fd))
            return details

        def assert_ffmpeg_fd(command, *args, **kwargs):
            (pinned_path, fd) = inspected[0]
            self.assertIn(pinned_path, command)
            self.assertEqual(kwargs.get("pass_fds"), (fd,))
            self.assertEqual(os.fstat(fd).st_ino, safe_inode)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_trim._probe_pinned_audio", side_effect=swap_after_probe):
            with patch("services.audio_trim.subprocess.run", side_effect=assert_ffmpeg_fd):
                trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertTrue(backup.is_file())
        self.assertAlmostEqual(probe_audio(self.target)["seconds"], 2.0, delta=0.25)
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_preexisting_target_remains_untouched(self):
        self.target.write_bytes(b"preexisting")
        with self.assertRaisesRegex(ValueError, "уже существует"):
            trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertEqual(self.target.read_bytes(), b"preexisting")
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_symlink_target_does_not_overwrite_referenced_file(self):
        protected = self.root / "protected.mp3"
        protected.write_bytes(b"do-not-change")
        self.target.symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "уже существует"):
            trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertEqual(protected.read_bytes(), b"do-not-change")
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_concurrent_target_creation_does_not_overwrite(self):
        real_probe = probe_audio
        def create_target_before_install(source, *, exact):
            result = real_probe(source, exact=exact)
            self.target.write_bytes(b"concurrent")
            return result

        with patch("services.audio_trim.probe_audio", side_effect=create_target_before_install):
            with self.assertRaisesRegex(ValueError, "уже существует"):
                trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertEqual(self.target.read_bytes(), b"concurrent")
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_oversized_source_inode_rejected_before_ffprobe(self):
        inflated = self.root / "inflated.wav"
        with inflated.open("wb") as stream:
            stream.write(self.source.read_bytes()[:44])
            stream.truncate(MAX_AUDIO_INPUT_BYTES + 1)
        with patch("services.audio_trim._probe_pinned_audio") as inspected:
            with self.assertRaisesRegex(ValueError, "20 МБ"):
                trim_audio(inflated, self.target, "00:00:01-00:00:03")
            inspected.assert_not_called()
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_timeout_cleans_staged_output(self):
        with patch("services.audio_trim._probe_pinned_audio",
                   return_value={"seconds": 5.0, "codec": "pcm_s16le"}):
            with patch("services.audio_trim.subprocess.run",
                       side_effect=subprocess.TimeoutExpired(["ffmpeg"], 65)):
                with self.assertRaisesRegex(ValueError, "лимит времени"):
                    trim_audio(self.source, self.target, "00:00:01-00:00:03")
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])

    def test_disguised_manifest_rejected_without_output(self):
        fake = self.root / "fake.wav"
        fake.write_text("ffconcat version 1.0\nfile five_seconds.wav\n")
        with self.assertRaises(ValueError):
            trim_audio(fake, self.target, "00:00:01-00:00:03")
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".fileshape-audio-trim-*")), [])


if __name__ == "__main__":
    unittest.main()
