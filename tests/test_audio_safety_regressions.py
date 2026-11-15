"""Regression coverage for bounded, content-neutral audio processing.

Fixtures are generated locally from silence and a solid-color video; no media
assets, soundtracks, or user files are stored in the repository.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.audio_tools import convert_audio, probe_audio


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealMediaSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wav = self.root / "silence.wav"
        with wave.open(str(self.wav), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\\x00\\x00" * 16000)

    def test_reject_video_bearing_container(self):
        video = self.root / "video.mp4"
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=16x16:r=1:d=1",
             "-i", str(self.wav), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(video)],
            capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        with self.assertRaisesRegex(ValueError, "без видеодорожки"):
            probe_audio(video)
        output = self.root / "converted.mp3"
        with self.assertRaises(ValueError):
            convert_audio(video, output, "mp3")
        self.assertFalse(output.exists())

    def test_corrupt_audio_and_invalid_target_do_not_create_output(self):
        invalid = self.root / "corrupt.wav"
        invalid.write_bytes(b"RIFF" + b"\\x00" * 12)
        with self.assertRaises(ValueError):
            probe_audio(invalid)
        output = self.root / "result.mp3"
        with self.assertRaises(ValueError):
            convert_audio(invalid, output, "mp3")
        self.assertFalse(output.exists())
        wrong = self.root / "wrong.bin"
        with self.assertRaises(ValueError):
            convert_audio(self.wav, wrong, "mp3")
        self.assertFalse(wrong.exists())

    def test_real_conversion_preserves_duration_and_container(self):
        for fmt in ("mp3", "ogg", "wav"):
            with self.subTest(fmt=fmt):
                output = self.root / ("converted." + fmt)
                convert_audio(self.wav, output, fmt)
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size, 0)
                self.assertAlmostEqual(probe_audio(output)["seconds"], 1, delta=0.2)


class ProbeFailureTests(unittest.TestCase):
    def test_overlong_duration_is_rejected(self):
        payload = {"format": {"duration": "601"}, "streams": [
            {"codec_type": "audio", "codec_name": "pcm_s16le"}]}
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with patch("services.audio_tools._program", return_value="ffprobe"), patch(
            "services.audio_tools.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(ValueError, "10 минут"):
                probe_audio(Path("/not-used.wav"))

    def test_probe_timeout_is_reported(self):
        with patch("services.audio_tools._program", return_value="ffprobe"), patch(
            "services.audio_tools.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["ffprobe"], 12),
        ):
            with self.assertRaisesRegex(ValueError, "отведённое время"):
                probe_audio(Path("/not-used.wav"))

    def test_ffmpeg_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.mp3"
            with patch("services.audio_tools.probe_audio", return_value={
                "seconds": 1, "codec": "pcm_s16le"
            }), patch("services.audio_tools._program", return_value="ffmpeg"), patch(
                "services.audio_tools.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["ffmpeg"], 65),
            ):
                with self.assertRaisesRegex(ValueError, "лимит времени"):
                    convert_audio(Path(directory) / "source.wav", output, "mp3")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
