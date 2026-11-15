"""M4A reference isolation and FFprobe JSON shape regressions.

All test recordings are generated as digital silence; no media assets stored.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from services.audio_join import join_audio
from services.audio_tools import convert_audio, probe_audio
from services.audio_trim import trim_audio


def make_silence(path: Path, seconds=3):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * (16000 * seconds))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class M4aInputIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.wav = self.root / "source.wav"
        self.m4a = self.root / "source.m4a"
        make_silence(self.wav)
        created = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-y", "-i", str(self.wav), "-c:a", "aac", str(self.m4a)],
            capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(created.returncode, 0, created.stderr.decode(errors="replace"))

    def assert_mov_guard(self, command):
        self.assertIn("-enable_drefs", command)
        self.assertEqual(command[command.index("-enable_drefs") + 1], "0")
        self.assertIn("-use_absolute_path", command)
        self.assertEqual(command[command.index("-use_absolute_path") + 1], "0")
        self.assertIn("-protocol_whitelist", command)
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file,pipe")

    def test_real_m4a_probe_and_convert_apply_mov_guard_to_source_only(self):
        real_run = subprocess.run
        recorded = []
        source_ino = self.m4a.stat().st_ino

        def inspect(command, *args, **kwargs):
            if Path(command[0]).name in ("ffprobe", "ffmpeg"):
                fds = kwargs.get("pass_fds", ())
                if fds and os.fstat(fds[0]).st_ino == source_ino:
                    recorded.append(command)
                    self.assert_mov_guard(command)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_tools.subprocess.run", side_effect=inspect):
            self.assertAlmostEqual(probe_audio(self.m4a)["seconds"], 3, delta=0.15)
            target = self.root / "converted.mp3"
            convert_audio(self.m4a, target, "mp3")
        self.assertTrue(target.is_file())
        self.assertEqual(probe_audio(target)["codec"], "mp3")
        self.assertEqual([Path(c[0]).name for c in recorded],
                         ["ffprobe", "ffprobe", "ffmpeg"])

    def test_wav_inputs_remain_compatible_without_mov_only_options(self):
        real_run = subprocess.run
        source_ino = self.wav.stat().st_ino
        commands = []

        def inspect(command, *args, **kwargs):
            fds = kwargs.get("pass_fds", ())
            if fds and os.fstat(fds[0]).st_ino == source_ino:
                commands.append(command)
                self.assertNotIn("-enable_drefs", command)
                self.assertNotIn("-use_absolute_path", command)
            return real_run(command, *args, **kwargs)

        target = self.root / "from-wav.ogg"
        with patch("services.audio_tools.subprocess.run", side_effect=inspect):
            self.assertEqual(probe_audio(self.wav)["codec"], "pcm_s16le")
            convert_audio(self.wav, target, "ogg")
        self.assertEqual(probe_audio(target)["codec"], "opus")
        self.assertGreaterEqual(len(commands), 3)

    def test_m4a_trim_uses_same_protected_inode_and_mov_flags(self):
        real_run = subprocess.run
        observed = []
        input_ino = self.m4a.stat().st_ino

        def inspect(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                self.assertEqual(len(kwargs["pass_fds"]), 1)
                self.assertEqual(os.fstat(kwargs["pass_fds"][0]).st_ino, input_ino)
                self.assert_mov_guard(command)
                observed.append(command)
            return real_run(command, *args, **kwargs)

        target = self.root / "trim.mp3"
        with patch("services.audio_trim.subprocess.run", side_effect=inspect):
            result = trim_audio(self.m4a, target, "00:00:00-00:00:02")
        self.assertEqual(len(observed), 1)
        self.assertEqual(result["output_format"], "mp3")
        self.assertAlmostEqual(probe_audio(target)["seconds"], 2, delta=0.25)

    def test_mixed_wav_m4a_join_only_guards_m4a_input(self):
        real_run = subprocess.run
        observed = []
        original_inodes = (self.wav.stat().st_ino, self.m4a.stat().st_ino)

        def inspect(command, *args, **kwargs):
            if "-filter_complex" in command:
                fds = kwargs["pass_fds"]
                self.assertEqual(tuple(os.fstat(fd).st_ino for fd in fds),
                                 original_inodes)
                inputs = [i for i, term in enumerate(command) if term == "-i"]
                self.assertEqual(len(inputs), 2)
                self.assertNotIn("-enable_drefs", command[:inputs[0]])
                self.assertEqual(command[inputs[1] - 4:inputs[1]],
                                 ["-enable_drefs", "0", "-use_absolute_path", "0"])
                observed.append(command)
            return real_run(command, *args, **kwargs)

        target = self.root / "joined.mp3"
        with patch("services.audio_join.subprocess.run", side_effect=inspect):
            result = join_audio([self.wav, self.m4a], target)
        self.assertEqual(len(observed), 1)
        self.assertEqual(result["inputs"], 2)
        self.assertTrue(target.is_file())
        self.assertAlmostEqual(probe_audio(target)["seconds"], 6, delta=0.3)

    def test_disguised_m4a_header_not_filename_controls_demuxer_flags(self):
        renamed = self.root / "mislabeled.wav"
        shutil.copyfile(self.m4a, renamed)
        real_run = subprocess.run
        seen = []

        def inspect(command, *args, **kwargs):
            if Path(command[0]).name == "ffprobe":
                self.assert_mov_guard(command)
                seen.append(True)
            return real_run(command, *args, **kwargs)

        with patch("services.audio_tools.subprocess.run", side_effect=inspect):
            self.assertAlmostEqual(probe_audio(renamed)["seconds"], 3, delta=0.2)
        self.assertEqual(len(seen), 1)

    def test_malformed_ffprobe_json_is_bounded_value_error_and_no_output(self):
        invalid = (
            None, [], "unexpected", {"format": None, "streams": []},
            {"format": [], "streams": []},
            {"format": {"format_name": "wav", "duration": "3"},
             "streams": "broken"},
            {"format": {"format_name": "wav", "duration": "3"},
             "streams": [None]},
            {"format": {"format_name": "wav", "duration": "3"},
             "streams": [123]},
        )
        for metadata in invalid:
            with self.subTest(metadata=repr(metadata)):
                response = subprocess.CompletedProcess(
                    ["ffprobe"], 0, json.dumps(metadata), ""
                )
                target = self.root / "should-not-exist.mp3"
                with patch("services.audio_tools.subprocess.run", return_value=response):
                    with self.assertRaisesRegex(ValueError, "Не удалось определить"):
                        probe_audio(self.wav)
                    with self.assertRaises(ValueError):
                        convert_audio(self.wav, target, "mp3")
                self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".fileshape-audio-convert-*")), [])


if __name__ == "__main__":
    unittest.main()
