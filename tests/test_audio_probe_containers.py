"""Regression tests for self-contained audio probing; no media assets committed."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.audio_tools import convert_audio, probe_audio


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioContainerSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.wav = self.root / "quiet.wav"
        with wave.open(str(self.wav), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * 16000)

    def test_real_supported_containers_and_exact_duration(self):
        outputs = {
            "mp3": ["-c:a", "libmp3lame"],
            "ogg": ["-c:a", "libopus"],
            "flac": ["-c:a", "flac"],
            "m4a": ["-c:a", "aac"],
        }
        self.assertAlmostEqual(probe_audio(self.wav, exact=True)["seconds"], 1.0, delta=0.01)
        for extension, codec in outputs.items():
            with self.subTest(extension=extension):
                media = self.root / ("quiet." + extension)
                made = subprocess.run(
                    ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                     "-y", "-i", str(self.wav), *codec, str(media)],
                    capture_output=True, check=False, timeout=20,
                )
                self.assertEqual(made.returncode, 0, made.stderr.decode(errors="replace"))
                self.assertAlmostEqual(probe_audio(media)["seconds"], 1.0, delta=0.15)
                info = probe_audio(media, exact=True)
                self.assertGreater(info["seconds"], 0)
                self.assertEqual(set(info), {"seconds", "codec"})

    def test_disguised_playlist_does_not_launch_ffprobe_or_ffmpeg(self):
        manifest = self.root / "seems-valid.wav"
        manifest.write_text("ffconcat version 1.0\nfile quiet.wav\nduration 1\n")
        output = self.root / "output.mp3"
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "аудиоконтейнер"):
                probe_audio(manifest)
            with self.assertRaisesRegex(ValueError, "аудиоконтейнер"):
                convert_audio(manifest, output, "mp3")
            run.assert_not_called()
        self.assertFalse(output.exists())

    def test_reject_unsafe_demuxer_even_with_audio_like_header(self):
        mock = subprocess.CompletedProcess([], 0, json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
            "format": {"format_name": "concat", "duration": "1.0"},
        }), "")
        with patch("services.audio_tools.subprocess.run", return_value=mock):
            with self.assertRaisesRegex(ValueError, "аудиоконтейнер"):
                probe_audio(self.wav)

    def test_reject_symlink_input_before_subprocess(self):
        link = self.root / "alias.wav"
        link.symlink_to(self.wav)
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaises(ValueError):
                probe_audio(link)
            run.assert_not_called()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_reject_fifo_without_blocking(self):
        fifo = self.root / "pretend.wav"
        os.mkfifo(fifo)
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaises(ValueError):
                probe_audio(fifo)
            run.assert_not_called()

    def test_corrupt_header_rejected_before_probe(self):
        invalid = self.root / "fake.mp3"
        invalid.write_bytes(b"not actually audio")
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "аудиоконтейнер"):
                probe_audio(invalid)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
