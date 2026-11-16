"""Atomic, no-clobber audio conversion tests. Only generated digital silence."""

import shutil
import stat
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.audio_tools import convert_audio, probe_audio


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AtomicAudioConversionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source.wav"
        self.target = self.root / "result.mp3"
        with wave.open(str(self.source), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * 16000)

    def assert_no_scratch(self):
        self.assertEqual(list(self.root.glob(".fileshape-audio-convert-*")), [])

    def test_real_mp3_ogg_wav_conversion_and_private_result(self):
        for fmt, codec in (("mp3", "mp3"), ("ogg", "opus"), ("wav", "pcm_s16le")):
            with self.subTest(fmt=fmt):
                target = self.root / ("result." + fmt)
                source_info = convert_audio(self.source, target, fmt)
                result_info = probe_audio(target, exact=True)
                self.assertTrue(target.is_file())
                self.assertEqual(source_info["codec"], "pcm_s16le")
                self.assertAlmostEqual(source_info["seconds"], 1, delta=0.1)
                self.assertEqual(result_info["codec"], codec)
                self.assertAlmostEqual(result_info["seconds"], 1, delta=0.3)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assert_no_scratch()

    def test_preexisting_result_is_not_modified_or_probed(self):
        self.target.write_bytes(b"previous result")
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "уже существует"):
                convert_audio(self.source, self.target, "mp3")
            run.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"previous result")
        self.assert_no_scratch()

    def test_symlink_and_dangling_symlink_results_blocked(self):
        protected = self.root / "private.mp3"
        protected.write_bytes(b"must survive")
        for existing_target in (protected, self.root / "not-yet-existing.mp3"):
            with self.subTest(target=existing_target):
                if self.target.is_symlink():
                    self.target.unlink()
                self.target.symlink_to(existing_target)
                with self.assertRaisesRegex(ValueError, "уже существует"):
                    convert_audio(self.source, self.target, "mp3")
                self.assert_no_scratch()
        self.assertEqual(protected.read_bytes(), b"must survive")
        self.target.unlink()

    def test_source_target_identity_never_truncates_original(self):
        original = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "уже существует"):
            convert_audio(self.source, self.source, "wav")
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_no_scratch()

    def test_timeout_cleans_partially_written_output(self):
        real_run = subprocess.run

        def partial_then_timeout(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                Path(command[-1]).write_bytes(b"partial")
                raise subprocess.TimeoutExpired(command, 65)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_tools.subprocess.run", side_effect=partial_then_timeout):
            with self.assertRaisesRegex(ValueError, "лимит времени"):
                convert_audio(self.source, self.target, "mp3")
        self.assertFalse(self.target.exists())
        self.assert_no_scratch()

    def test_ffmpeg_failure_with_partial_bytes_cleans_output(self):
        real_run = subprocess.run

        def unsuccessful(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                Path(command[-1]).write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 1)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_tools.subprocess.run", side_effect=unsuccessful):
            with self.assertRaisesRegex(ValueError, "Не получилось"):
                convert_audio(self.source, self.target, "mp3")
        self.assertFalse(self.target.exists())
        self.assert_no_scratch()

    def test_corrupt_successful_output_does_not_publish(self):
        real_run = subprocess.run

        def fake_success(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                Path(command[-1]).write_bytes(b"not audio")
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_tools.subprocess.run", side_effect=fake_success):
            with self.assertRaises(ValueError):
                convert_audio(self.source, self.target, "mp3")
        self.assertFalse(self.target.exists())
        self.assert_no_scratch()

    def test_concurrent_target_creation_preserves_existing_data(self):
        true_probe = probe_audio

        def inject_collision(stage, *, exact=False):
            info = true_probe(stage, exact=exact)
            self.target.write_bytes(b"another writer won")
            return info

        with patch("services.audio_tools.probe_audio", side_effect=inject_collision):
            with self.assertRaisesRegex(ValueError, "уже существует"):
                convert_audio(self.source, self.target, "mp3")
        self.assertEqual(self.target.read_bytes(), b"another writer won")
        self.assert_no_scratch()

    def test_reject_symlinked_output_parent(self):
        linked_dir = self.root / "linked"
        linked_dir.symlink_to(self.root, target_is_directory=True)
        target = linked_dir / "result.mp3"
        with self.assertRaisesRegex(ValueError, "каталог"):
            convert_audio(self.source, target, "mp3")
        self.assert_no_scratch()

    def test_target_format_validation_prevents_scratch_creation(self):
        wrong = self.root / "wrong.wav"
        with self.assertRaisesRegex(ValueError, "формат"):
            convert_audio(self.source, wrong, "mp3")
        self.assertFalse(wrong.exists())
        self.assert_no_scratch()


if __name__ == "__main__":
    unittest.main()
