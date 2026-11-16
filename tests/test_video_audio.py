"""Real generated neutral media tests for secure MP4/MOV audio extraction."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.audio_tools import probe_audio
from services.video_audio import (
    MAX_VIDEO_INPUT_BYTES, _probe_pinned_video, extract_audio_from_video,
)


def render_video(path: Path, *, include_video: bool = True,
                 include_audio: bool = True) -> None:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if include_video:
        command += ["-f", "lavfi", "-i", "color=c=black:s=16x16:r=10:d=1"]
    if include_audio:
        command += ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono"]
    command += ["-t", "1"]
    if include_video:
        command += ["-c:v", "mpeg4"]
    else:
        command += ["-vn"]
    if include_audio:
        command += ["-c:a", "aac"]
    else:
        command += ["-an"]
    command.append(str(path))
    created = subprocess.run(command, capture_output=True, check=False, timeout=25)
    if created.returncode != 0:
        raise AssertionError(created.stderr.decode(errors="replace"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoAudioExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.mp4"
        self.target = self.root / "audio.mp3"
        render_video(self.source)

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob(".fileshape-video-audio-*")), [])

    def test_real_mp4_and_mov_audio_only_private_mp3(self):
        for suffix in (".mp4", ".mov"):
            with self.subTest(suffix=suffix):
                source = self.source
                if suffix == ".mov":
                    source = self.root / "source.mov"
                    render_video(source)
                target = self.root / ("result-" + suffix.lstrip(".") + ".mp3")
                details = extract_audio_from_video(source, target)
                self.assertTrue(target.is_file())
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(details["codec"], "mp3")
                self.assertAlmostEqual(details["source_seconds"], 1.0, delta=0.1)
                self.assertAlmostEqual(details["seconds"], 1.0, delta=0.2)
                self.assertEqual(probe_audio(target)["codec"], "mp3")
                self.assert_no_staging()

    def test_external_movie_references_explicitly_disabled(self):
        original_run = subprocess.run
        with patch("services.video_audio.subprocess.run",
                   side_effect=original_run) as invoked:
            extract_audio_from_video(self.source, self.target)
        video_commands = [
            call.args[0] for call in invoked.call_args_list
            if "-enable_drefs" in call.args[0]
        ]
        self.assertEqual(len(video_commands), 2)
        for command in video_commands:
            with self.subTest(program=Path(command[0]).name):
                self.assertEqual(command[command.index("-enable_drefs") + 1], "0")
                self.assertEqual(command[command.index("-use_absolute_path") + 1], "0")
                self.assertEqual(command[command.index("-protocol_whitelist") + 1],
                                 "file,pipe")
        self.assert_no_staging()

    def test_bad_probe_json_shapes_fail_cleanly(self):
        malformed = (
            None,
            [],
            {"format": None, "streams": []},
            {"format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
             "streams": "invalid"},
            {"format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
             "streams": [None]},
        )
        for payload in malformed:
            with self.subTest(payload=repr(payload)):
                checked = subprocess.CompletedProcess(
                    [], 0, json.dumps(payload), ""
                )
                with patch("services.video_audio.subprocess.run",
                           return_value=checked):
                    with self.assertRaises(ValueError):
                        extract_audio_from_video(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assert_no_staging()

    def test_no_audio_stream_or_no_video_stream_is_rejected(self):
        for audio, video in ((False, True), (True, False)):
            with self.subTest(audio=audio, video=video):
                source = self.root / ("only_audio.mp4" if audio else "only_video.mp4")
                render_video(source, include_video=video, include_audio=audio)
                with self.assertRaisesRegex(ValueError, "видеоряд и аудиодорожку"):
                    extract_audio_from_video(source, self.target)
                self.assertFalse(self.target.exists())
                self.assert_no_staging()

    def test_reject_bad_extension_corrupt_container_and_manifest(self):
        with self.assertRaisesRegex(ValueError, "MP4 и MOV"):
            extract_audio_from_video(self.root / "clip.webm", self.target)
        fake = self.root / "broken.mp4"
        fake.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"broken")
        with self.assertRaises(ValueError):
            extract_audio_from_video(fake, self.target)
        manifest = self.root / "manifest.mp4"
        manifest.write_text("ffconcat version 1.0\nfile source.mp4\n")
        with patch("services.video_audio.subprocess.run") as invoked:
            with self.assertRaises(ValueError):
                extract_audio_from_video(manifest, self.target)
            invoked.assert_not_called()
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_source_symlink_and_oversized_inode_fail_without_staging(self):
        link = self.root / "link.mp4"
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            extract_audio_from_video(link, self.target)
        oversize = self.root / "large.mp4"
        shutil.copyfile(self.source, oversize)
        with oversize.open("r+b") as out:
            out.truncate(MAX_VIDEO_INPUT_BYTES + 1)
        with patch("services.video_audio._probe_pinned_video") as inspected:
            with self.assertRaisesRegex(ValueError, "50 МиБ"):
                extract_audio_from_video(oversize, self.target)
            inspected.assert_not_called()
        self.assertFalse(self.target.exists())
        self.assert_no_staging()

    def test_preserves_output_and_symlink_target(self):
        self.target.write_bytes(b"preexisting")
        with self.assertRaisesRegex(ValueError, "уже существует"):
            extract_audio_from_video(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"preexisting")
        self.target.unlink()
        protected = self.root / "protected.mp3"
        protected.write_bytes(b"never overwrite")
        self.target.symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "уже существует"):
            extract_audio_from_video(self.source, self.target)
        self.assertEqual(protected.read_bytes(), b"never overwrite")
        self.assert_no_staging()

    def test_replacement_between_probe_and_encoding_keeps_same_inode(self):
        original_inode = self.source.stat().st_ino
        backup = self.root / "preserved.mp4"
        real_probe = _probe_pinned_video
        real_run = subprocess.run
        inspected = []

        def replace_on_probe(pinned_path, fd):
            duration = real_probe(pinned_path, fd)
            self.source.rename(backup)
            self.source.write_text("ffconcat version 1.0\nfile preserved.mp4\n")
            inspected.append((pinned_path, fd))
            return duration

        def verify_encoder(command, *args, **kwargs):
            if "-map" in command:
                pinned_path, fd = inspected[0]
                self.assertIn(pinned_path, command)
                self.assertEqual(kwargs["pass_fds"], (fd,))
                self.assertEqual(os.fstat(fd).st_ino, original_inode)
            return real_run(command, *args, **kwargs)

        with patch("services.video_audio._probe_pinned_video",
                   side_effect=replace_on_probe):
            with patch("services.video_audio.subprocess.run",
                       side_effect=verify_encoder):
                info = extract_audio_from_video(self.source, self.target)
        self.assertEqual(len(inspected), 1)
        self.assertAlmostEqual(info["seconds"], 1.0, delta=0.2)
        self.assertTrue(backup.exists())
        self.assert_no_staging()

    def test_concurrent_target_creation_cannot_overwrite(self):
        real_probe = probe_audio

        def create_target_after_encode(media):
            info = real_probe(media)
            self.target.write_bytes(b"concurrent")
            return info

        with patch("services.video_audio.probe_audio",
                   side_effect=create_target_after_encode):
            with self.assertRaisesRegex(ValueError, "уже существует"):
                extract_audio_from_video(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"concurrent")
        self.assert_no_staging()

    def test_ffmpeg_timeout_and_failed_process_cleanup(self):
        for failure in (
            subprocess.TimeoutExpired(["ffmpeg"], 65),
            subprocess.CompletedProcess(["ffmpeg"], 1),
        ):
            with self.subTest(failure=type(failure).__name__):
                with patch("services.video_audio._probe_pinned_video",
                           return_value=1.0):
                    with patch("services.video_audio.subprocess.run",
                               side_effect=failure if isinstance(failure, Exception) else None,
                               return_value=failure if not isinstance(failure, Exception) else None):
                        with self.assertRaises(ValueError):
                            extract_audio_from_video(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assert_no_staging()

    def test_reject_unexpected_demuxer_and_overlong_probe(self):
        for format_name, seconds, message in (
            ("concat", "1.0", "видеоконтейнер"),
            ("mov,mp4,m4a,3gp,3g2,mj2", "601.0", "10 минут"),
        ):
            payload = json.dumps({
                "format": {"format_name": format_name, "duration": seconds},
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            })
            done = subprocess.CompletedProcess([], 0, payload, "")
            with self.subTest(format=format_name, seconds=seconds):
                with patch("services.video_audio.subprocess.run", return_value=done):
                    with self.assertRaisesRegex(ValueError, message):
                        extract_audio_from_video(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assert_no_staging()


if __name__ == "__main__":
    unittest.main()
