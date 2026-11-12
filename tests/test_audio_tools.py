"""Audio conversion regression tests using tiny generated PCM audio."""
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from services.audio_tools import convert_audio, probe_audio


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class AudioToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "sample.wav"
        with wave.open(str(self.source), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * 8000)

    def test_audio_probe(self):
        info = probe_audio(self.source)
        self.assertAlmostEqual(info["seconds"], 0.5, delta=0.1)
        self.assertIn("pcm", info["codec"])

    def test_audio_convert_formats(self):
        for target_format in ("mp3", "ogg", "wav"):
            with self.subTest(format=target_format):
                target = self.folder / ("out." + target_format)
                convert_audio(self.source, target, target_format)
                self.assertTrue(target.exists())
                self.assertGreater(target.stat().st_size, 100)
                self.assertAlmostEqual(probe_audio(target)["seconds"], 0.5, delta=0.15)

    def test_reject_wrong_format_and_bad_media(self):
        with self.assertRaises(ValueError):
            convert_audio(self.source, self.folder / "wrong.bin", "mp3")
        fake = self.folder / "fake.mp3"
        fake.write_bytes(b"not really an audio file")
        with self.assertRaises(ValueError):
            probe_audio(fake)


if __name__ == "__main__":
    unittest.main()
