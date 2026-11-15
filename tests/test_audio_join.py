"""Content-neutral audio-join tests with generated silent media only."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from services.audio_join import (
    MAX_JOIN_FILE_BYTES, join_audio,
)
from services.audio_tools import probe_audio


def make_silence(path: Path, seconds: float, rate: int):
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x00" * round(seconds * rate))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealAudioJoinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.a = self.dir / "a.wav"
        self.b = self.dir / "b.wav"
        make_silence(self.a, 0.4, 8000)
        make_silence(self.b, 0.7, 16000)
        self.target = self.dir / "joined.mp3"

    def test_mixed_sample_rates_order_and_real_output(self):
        real_run = subprocess.run
        with patch("services.audio_join.subprocess.run", side_effect=real_run) as run_calls:
            info = join_audio([self.b, self.a], self.target)
        encoder_calls = [call for call in run_calls.call_args_list
                         if "-filter_complex" in call.args[0]]
        self.assertEqual(len(encoder_calls), 1)
        encode = encoder_calls[0]
        cmd = encode.args[0]
        self.assertEqual(
            [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-i"],
            [f"/proc/self/fd/{fd}" for fd in encode.kwargs["pass_fds"]],
        )
        self.assertEqual(len(encode.kwargs["pass_fds"]), 2)
        self.assertEqual(info["inputs"], 2)
        self.assertTrue(self.target.is_file())
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertIn(probe_audio(self.target)["codec"], ("mp3",))
        self.assertAlmostEqual(info["seconds"], 1.1, delta=0.2)
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_five_inputs_at_limit(self):
        sources = []
        for index in range(5):
            part = self.dir / f"segment_{index}.wav"
            make_silence(part, 0.2, 8000 + index * 2000)
            sources.append(part)
        info = join_audio(sources, self.target)
        self.assertEqual(info["inputs"], 5)
        self.assertAlmostEqual(probe_audio(self.target)["seconds"], 1.0, delta=0.2)
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_reject_invalid_count(self):
        for sources in ([], [self.a], [self.a] * 6):
            with self.subTest(size=len(sources)), self.assertRaisesRegex(ValueError, "от 2 до 5"):
                join_audio(sources, self.target)
        self.assertFalse(self.target.exists())

    def test_reject_malformed_media_and_partial_output(self):
        self.b.write_bytes(b"not audio")
        with self.assertRaises(ValueError):
            join_audio([self.a, self.b], self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_reject_symlink_and_oversize_before_processing(self):
        alias = self.dir / "alias.wav"
        alias.symlink_to(self.a)
        with self.assertRaises(ValueError):
            join_audio([alias, self.b], self.target)
        too_large = self.dir / "large.wav"
        with too_large.open("wb") as out:
            out.truncate(MAX_JOIN_FILE_BYTES + 1)
        with self.assertRaises(ValueError):
            join_audio([self.a, too_large], self.target)
        self.assertFalse(self.target.exists())

    def test_reject_total_bytes_before_ffmpeg(self):
        large = []
        for number in range(3):
            part = self.dir / f"large_{number}.wav"
            make_silence(part, 0.02, 8000)
            with part.open("r+b") as stream:
                stream.truncate(18 * 1024 * 1024)
            large.append(part)
        with patch("services.audio_join._probe_pinned_audio", return_value={
            "seconds": 1.0, "codec": "pcm_s16le"
        }) as checked:
            with self.assertRaisesRegex(ValueError, "50 МиБ"):
                join_audio(large, self.target)
        self.assertEqual(checked.call_count, 2)
        self.assertFalse(self.target.exists())

    def test_reject_video_bearing_mp4(self):
        mp4 = self.dir / "video.mp4"
        made = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=16x16:r=10:d=1",
            "-i", str(self.a), "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(mp4)
        ], capture_output=True, timeout=20, check=False)
        self.assertEqual(made.returncode, 0, made.stderr.decode(errors="replace"))
        with self.assertRaisesRegex(ValueError, "без видеодорожки"):
            join_audio([self.a, mp4], self.target)
        self.assertFalse(self.target.exists())

    def test_no_clobber_of_existing_file(self):
        self.target.write_bytes(b"preexisting")
        with self.assertRaisesRegex(ValueError, "уже существует"):
            join_audio([self.a, self.b], self.target)
        self.assertEqual(self.target.read_bytes(), b"preexisting")

    def test_reject_duration_over_limit(self):
        with patch("services.audio_join._probe_pinned_audio", side_effect=[
            {"seconds": 400, "codec": "pcm_s16le"},
            {"seconds": 300, "codec": "pcm_s16le"},
        ]):
            with self.assertRaisesRegex(ValueError, "10 минут"):
                join_audio([self.a, self.b], self.target)
        self.assertFalse(self.target.exists())

    def test_rounded_durations_cannot_silently_truncate_result(self):
        # Each file is 300.04s but the public probe returns 300.0s.
        # Rounding would incorrectly permit 600.08s and FFmpeg -t 600
        # would silently cut part of the last recording.
        a = self.dir / "long_a.wav"
        b = self.dir / "long_b.wav"
        make_silence(a, 300.04, 8000)
        make_silence(b, 300.04, 8000)
        self.assertEqual(probe_audio(a)["seconds"], 300.0)
        self.assertEqual(probe_audio(b)["seconds"], 300.0)

        def probe_only(binary):
            if binary == "ffmpeg":
                self.fail("FFmpeg must not start for an overlong join")
            return shutil.which(binary)

        with patch("services.audio_join._program", side_effect=probe_only):
            with self.assertRaisesRegex(ValueError, "10 минут"):
                join_audio([a, b], self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_replaced_input_path_still_uses_original_inode(self):
        real_probe = __import__(
            "services.audio_join", fromlist=["_probe_pinned_audio"]
        )._probe_pinned_audio
        real_run = subprocess.run
        initial = [self.a.stat().st_ino, self.b.stat().st_ino]
        held = []
        saved = self.dir / "original-b.wav"
        checked_encoder = []

        def probe_then_replace(path, fd, *, exact):
            info = real_probe(path, fd, exact=exact)
            held.append((path, fd))
            if len(held) == 2:
                self.b.rename(saved)
                self.b.write_text("ffconcat version 1.0\\nfile original-b.wav\\n")
            return info

        def check_encoder(command, *args, **kwargs):
            if "-filter_complex" in command:
                checked_encoder.append(True)
                fds = kwargs["pass_fds"]
                self.assertEqual(tuple(fd for _, fd in held), fds)
                self.assertEqual([os.fstat(fd).st_ino for fd in fds], initial)
                self.assertEqual(
                    [command[i + 1] for i, value in enumerate(command)
                     if value == "-i"], [path for path, _ in held]
                )
            return real_run(command, *args, **kwargs)

        with patch("services.audio_join._probe_pinned_audio",
                   side_effect=probe_then_replace):
            with patch("services.audio_join.subprocess.run",
                       side_effect=check_encoder):
                details = join_audio([self.a, self.b], self.target)
        self.assertEqual(len(checked_encoder), 1)
        self.assertAlmostEqual(details["seconds"], 1.1, delta=0.2)
        self.assertTrue(saved.is_file())
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_concurrent_result_creation_cannot_overwrite(self):
        original_probe = probe_audio
        def create_target_during_validation(source):
            self.target.write_bytes(b"concurrent-result")
            return original_probe(source)
        with patch("services.audio_join.probe_audio",
                   side_effect=create_target_during_validation):
            with self.assertRaisesRegex(ValueError, "уже существует"):
                join_audio([self.a, self.b], self.target)
        self.assertEqual(self.target.read_bytes(), b"concurrent-result")
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_symlink_result_preserves_referenced_file(self):
        protected = self.dir / "protected.mp3"
        protected.write_bytes(b"protected")
        self.target.symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "уже существует"):
            join_audio([self.a, self.b], self.target)
        self.assertEqual(protected.read_bytes(), b"protected")
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_ffmpeg_timeout_cleans_intermediate(self):
        with patch("services.audio_join._probe_pinned_audio", return_value={
            "seconds": 1, "codec": "pcm_s16le"
        }), patch("services.audio_join.subprocess.run", side_effect=subprocess.TimeoutExpired(["ffmpeg"], 65)):
            with self.assertRaisesRegex(ValueError, "лимит времени"):
                join_audio([self.a, self.b], self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])

    def test_ffmpeg_failure_cleans_intermediate(self):
        with patch("services.audio_join._probe_pinned_audio", return_value={
            "seconds": 1, "codec": "pcm_s16le"
        }), patch("services.audio_join.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "Не удалось"):
                join_audio([self.a, self.b], self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.dir.glob(".fileshape-audio-join-*")), [])


if __name__ == "__main__":
    unittest.main()
