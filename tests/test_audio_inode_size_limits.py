"""Byte-limit regression tests for pinned, owner-workspace audio input.

All signals are generated silence. Large cases use sparse files; the tests
never allocate 20–50 MiB of RAM or invoke native tools on oversized inputs.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from services.audio_tools import (
    MAX_CONVERSION_INPUT_BYTES, MAX_PINNED_MEDIA_BYTES,
    _pinned_audio_source, convert_audio, probe_audio,
)
from services.video_audio import extract_audio_from_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class PinnedMediaSizeLimitsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.wav"
        self.output = self.root / "result.mp3"
        with wave.open(str(self.source), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\x00\x00" * 16000)

    def sparse_audio(self, size: int) -> Path:
        path = self.root / f"sparse-{size}.wav"
        with path.open("wb") as dest:
            dest.write(self.source.read_bytes())
            dest.truncate(size)
        return path

    def sparse_video(self, size: int) -> Path:
        path = self.root / f"video-{size}.mp4"
        with path.open("wb") as dest:
            dest.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isom")
            dest.truncate(size)
        return path

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".fileshape-audio-convert-*")), [])
        self.assertEqual(list(self.root.glob(".fileshape-video-audio-*")), [])

    def test_conversion_rejects_twenty_mib_plus_one_before_probe_or_ffmpeg(self):
        source = self.sparse_audio(MAX_CONVERSION_INPUT_BYTES + 1)
        with (
            patch("services.audio_tools._probe_pinned_audio") as probe,
            patch("services.audio_tools.subprocess.run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "20 МиБ"):
                convert_audio(source, self.output, "mp3")
            probe.assert_not_called()
            run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_exact_twenty_mib_reaches_probe_not_rejected_at_boundary(self):
        source = self.sparse_audio(MAX_CONVERSION_INPUT_BYTES)
        # Sentinel aborts after inode size check, before expensive encoding.
        with patch("services.audio_tools._probe_pinned_audio",
                   side_effect=RuntimeError("size boundary accepted")) as probe:
            with self.assertRaisesRegex(RuntimeError, "boundary accepted"):
                convert_audio(source, self.output, "mp3")
            probe.assert_called_once()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_probe_rejects_fifty_mib_plus_one_before_native_tool(self):
        source = self.sparse_audio(MAX_PINNED_MEDIA_BYTES + 1)
        with patch("services.audio_tools.subprocess.run") as runner:
            with self.assertRaisesRegex(ValueError, "50 МиБ"):
                probe_audio(source)
            runner.assert_not_called()
        self.assert_no_staging()

    def test_exact_fifty_mib_is_accepted_by_shared_pinned_media_gate(self):
        source = self.sparse_audio(MAX_PINNED_MEDIA_BYTES)
        with _pinned_audio_source(source) as (pinned_path, descriptor):
            self.assertEqual(os.fstat(descriptor).st_size, MAX_PINNED_MEDIA_BYTES)
            self.assertEqual(pinned_path, f"/proc/self/fd/{descriptor}")
        self.assert_no_staging()

    def test_zero_byte_regular_file_rejected_before_ffprobe(self):
        empty = self.root / "empty.wav"
        empty.touch()
        with patch("services.audio_tools.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "пустой"):
                probe_audio(empty)
            with self.assertRaisesRegex(ValueError, "пустой"):
                convert_audio(empty, self.output, "mp3")
            run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_video_over_fifty_mib_never_reaches_video_probe(self):
        source = self.sparse_video(MAX_PINNED_MEDIA_BYTES + 1)
        with patch("services.video_audio._probe_pinned_video") as probe:
            with self.assertRaisesRegex(ValueError, "50 МиБ"):
                extract_audio_from_video(source, self.output)
            probe.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_exact_fifty_mib_video_reaches_video_domain_validation(self):
        source = self.sparse_video(MAX_PINNED_MEDIA_BYTES)
        with patch("services.video_audio._probe_pinned_video",
                   side_effect=RuntimeError("video size accepted")) as probe:
            with self.assertRaisesRegex(RuntimeError, "video size accepted"):
                extract_audio_from_video(source, self.output)
            probe.assert_called_once()
        self.assertFalse(self.output.exists())
        self.assert_no_staging()

    def test_small_generated_wav_to_mp3_conversion_still_works(self):
        source_info = convert_audio(self.source, self.output, "mp3")
        self.assertTrue(self.output.is_file())
        self.assertEqual(probe_audio(self.output)["codec"], "mp3")
        self.assertAlmostEqual(source_info["seconds"], 1.0, delta=0.15)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assert_no_staging()


if __name__ == "__main__":
    unittest.main()
