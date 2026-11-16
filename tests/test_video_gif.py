"""Real-media and failure regressions for bounded MP4/MOV to animated GIF.

Only generated abstract test patterns and optional digital silence are used.
No video, sound, photos or other media fixtures are committed.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.video_gif import (
    MAX_GIF_SOURCE_BYTES, _probe_gif_video, _validate_gif, video_to_gif,
)


def render(path: Path, *, audio: bool = False, video: bool = True,
           duration: int = 2, size: str = "96x64", fps: int = 10) -> None:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if video:
        command += [
            "-f", "lavfi",
            "-i", f"testsrc2=size={size}:rate={fps}:duration={duration}",
        ]
    if audio:
        command += ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono"]
    command += ["-t", str(duration)]
    if video:
        command += ["-c:v", "mpeg4"]
    else:
        command += ["-vn"]
    if audio:
        command += ["-c:a", "aac"]
    else:
        command += ["-an"]
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, timeout=25, check=False)
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoGifTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.mp4"
        self.target = self.root / "result.gif"
        render(self.source)

    def no_stage(self):
        self.assertEqual(list(self.root.glob(".fileshape-video-gif-*")), [])

    def test_real_mp4_and_mov_with_or_without_silent_audio(self):
        for suffix, with_audio in ((".mp4", False), (".mov", True)):
            with self.subTest(suffix=suffix):
                source = self.root / ("clip" + suffix)
                render(source, audio=with_audio)
                output = self.root / ("clip-" + suffix[1:] + ".gif")
                report = video_to_gif(source, output)
                self.assertTrue(output.is_file())
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                self.assertLessEqual(output.stat().st_size, 8 * 1024 * 1024)
                self.assertAlmostEqual(report["source_seconds"], 2, delta=0.15)
                self.assertAlmostEqual(report["seconds"], 2, delta=0.5)
                self.assertGreaterEqual(report["frames"], 2)
                self.assertLessEqual(report["frames"], 16)
                self.assertEqual((report["width"], report["height"]), (96, 64))
                with Image.open(output) as frames:
                    self.assertEqual(frames.format, "GIF")
                    self.assertEqual(frames.n_frames, report["frames"])
                self.no_stage()

    def test_video_probe_and_encode_are_pinned_and_disable_external_mov(self):
        real_run = subprocess.run
        original_inode = self.source.stat().st_ino
        native = []

        def inspect(command, *args, **kwargs):
            executable = Path(command[0]).name
            if executable in ("ffprobe", "ffmpeg"):
                fds = kwargs.get("pass_fds")
                self.assertEqual(len(fds), 1)
                self.assertEqual(os.fstat(fds[0]).st_ino, original_inode)
                self.assertIn(f"/proc/self/fd/{fds[0]}", command)
                self.assertEqual(command[command.index("-enable_drefs") + 1], "0")
                self.assertEqual(command[command.index("-use_absolute_path") + 1], "0")
                self.assertEqual(command[command.index("-protocol_whitelist") + 1],
                                 "file,pipe")
                native.append(executable)
                if executable == "ffmpeg":
                    self.assertEqual(command[command.index("-map") + 1], "0:v:0")
                    self.assertIn("-an", command)
                    self.assertIn("-map_metadata", command)
                    self.assertIn("-frames:v", command)
            return real_run(command, *args, **kwargs)

        with patch("services.video_gif.subprocess.run", side_effect=inspect):
            video_to_gif(self.source, self.target)
        self.assertEqual(native, ["ffprobe", "ffmpeg"])
        self.no_stage()

    def test_source_path_replacement_keeps_same_validated_inode(self):
        old_inode = self.source.stat().st_ino
        saved = self.root / "preserved.mp4"
        real_probe = _probe_gif_video
        real_run = subprocess.run

        def swap_after_probe(pinned_path, fd):
            metadata = real_probe(pinned_path, fd)
            self.source.rename(saved)
            self.source.write_text("ffconcat version 1.0\nfile preserved.mp4\n")
            return metadata

        def verify_encode(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                self.assertEqual(os.fstat(kwargs["pass_fds"][0]).st_ino, old_inode)
                self.assertIn(f"/proc/self/fd/{kwargs['pass_fds'][0]}", command)
            return real_run(command, *args, **kwargs)

        with patch("services.video_gif._probe_gif_video", side_effect=swap_after_probe):
            with patch("services.video_gif.subprocess.run", side_effect=verify_encode):
                info = video_to_gif(self.source, self.target)
        self.assertTrue(saved.is_file())
        self.assertGreaterEqual(info["frames"], 2)
        self.no_stage()

    def test_no_video_stream_and_bad_extensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "MP4 и MOV"):
            video_to_gif(self.root / "movie.mkv", self.target)
        with self.assertRaisesRegex(ValueError, "GIF"):
            video_to_gif(self.source, self.root / "image.png")
        only_audio = self.root / "only-audio.mp4"
        render(only_audio, audio=True, video=False)
        with self.assertRaises(ValueError):
            video_to_gif(only_audio, self.target)
        self.assertFalse(self.target.exists())
        self.no_stage()

    def test_manifest_corrupt_header_or_symlink_never_launch_native_tool(self):
        invalid = self.root / "playlist.mp4"
        invalid.write_text("ffconcat version 1.0\nfile source.mp4\n")
        corrupt = self.root / "corrupt.mp4"
        corrupt.write_bytes(b"bad mp4")
        link = self.root / "alias.mp4"
        link.symlink_to(self.source)
        with patch("services.video_gif.subprocess.run") as run:
            for source in (invalid, corrupt, link):
                with self.subTest(source=source):
                    with self.assertRaises(ValueError):
                        video_to_gif(source, self.target)
            run.assert_not_called()
        self.assertFalse(self.target.exists())
        self.no_stage()

    def test_sparse_oversize_rejected_before_ffprobe(self):
        sparse = self.root / "large.mp4"
        shutil.copyfile(self.source, sparse)
        with sparse.open("r+b") as file:
            file.truncate(MAX_GIF_SOURCE_BYTES + 1)
        with patch("services.video_gif._probe_gif_video") as probe:
            with self.assertRaisesRegex(ValueError, "20 МиБ"):
                video_to_gif(sparse, self.target)
            probe.assert_not_called()
        self.no_stage()

    def test_long_video_rejected_before_encoding(self):
        long = self.root / "long.mp4"
        render(long, duration=9)
        with patch("services.video_gif.subprocess.run", wraps=subprocess.run) as runs:
            with self.assertRaisesRegex(ValueError, "8 секунд"):
                video_to_gif(long, self.target)
            self.assertEqual(len(runs.call_args_list), 1)
            self.assertEqual(Path(runs.call_args_list[0].args[0][0]).name, "ffprobe")
        self.no_stage()

    def test_high_fps_video_rejected(self):
        fast = self.root / "fast.mp4"
        render(fast, fps=70)
        with self.assertRaisesRegex(ValueError, "60 FPS"):
            video_to_gif(fast, self.target)
        self.no_stage()

    def test_high_resolution_video_rejected_without_encoding(self):
        large = self.root / "large-resolution.mp4"
        render(large, size="1920x1200", duration=1)
        with self.assertRaisesRegex(ValueError, "Разрешение"):
            video_to_gif(large, self.target)
        self.no_stage()

    def test_malformed_ffprobe_json_fails_before_encoding(self):
        original = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.0"},
            "streams": [{"codec_type": "video", "width": 96, "height": 64,
                         "avg_frame_rate": "10/1",
                         "disposition": {"attached_pic": 0}}],
        }
        malformed = [
            None, [], {"format": None, "streams": []},
            {"format": original["format"], "streams": [None]},
            {"format": original["format"], "streams": "broken"},
            {**original, "streams": [{**original["streams"][0],
                                     "avg_frame_rate": "0/0"}]},
            {**original, "streams": [{**original["streams"][0],
                                     "disposition": {"attached_pic": 1}}]},
            {**original, "streams": [{**original["streams"][0],
                                     "width": "96"}]},
        ]
        for payload in malformed:
            with self.subTest(value=repr(payload)):
                response = subprocess.CompletedProcess(
                    ["ffprobe"], 0, json.dumps(payload), ""
                )
                with patch("services.video_gif.subprocess.run", return_value=response):
                    with self.assertRaises(ValueError):
                        video_to_gif(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.no_stage()

    def test_preserve_existing_or_symlink_destination(self):
        original = b"do not overwrite this GIF"
        self.target.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "уже существует"):
            video_to_gif(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), original)
        self.target.unlink()
        protected = self.root / "private.gif"
        protected.write_bytes(original)
        self.target.symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "уже существует"):
            video_to_gif(self.source, self.target)
        self.assertEqual(protected.read_bytes(), original)
        self.target.unlink()
        self.target.symlink_to(self.root / "missing.gif")
        with self.assertRaisesRegex(ValueError, "уже существует"):
            video_to_gif(self.source, self.target)
        self.target.unlink()
        self.no_stage()

    def test_symlink_output_parent_rejected(self):
        alias = self.root / "alias-folder"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "каталог"):
            video_to_gif(self.source, alias / "out.gif")
        self.no_stage()

    def test_successful_encoder_returning_invalid_gif_never_publishes(self):
        real_run = subprocess.run

        def corrupt(command, *args, **kwargs):
            if Path(command[0]).name == "ffmpeg":
                Path(command[-1]).write_bytes(b"not an animated GIF")
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, *args, **kwargs)

        with patch("services.video_gif.subprocess.run", side_effect=corrupt):
            with self.assertRaises(ValueError):
                video_to_gif(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.no_stage()

    def test_failed_or_timed_out_ffmpeg_cleans_partial_output(self):
        real_run = subprocess.run
        for mode in ("error", "timeout"):
            with self.subTest(mode=mode):
                def fail(command, *args, **kwargs):
                    if Path(command[0]).name == "ffmpeg":
                        Path(command[-1]).write_bytes(b"partial GIF")
                        if mode == "timeout":
                            raise subprocess.TimeoutExpired(command, 45)
                        return subprocess.CompletedProcess(command, 1)
                    return real_run(command, *args, **kwargs)

                with patch("services.video_gif.subprocess.run", side_effect=fail):
                    with self.assertRaises(ValueError):
                        video_to_gif(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.no_stage()

    def test_racing_creation_of_target_cannot_overwrite(self):
        original_check = _validate_gif
        existing = b"another writer won"

        def collide(path, *, source_seconds):
            validated = original_check(path, source_seconds=source_seconds)
            self.target.write_bytes(existing)
            return validated

        with patch("services.video_gif._validate_gif", side_effect=collide):
            with self.assertRaisesRegex(ValueError, "уже существует"):
                video_to_gif(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), existing)
        self.no_stage()


if __name__ == "__main__":
    unittest.main()
