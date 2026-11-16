"""Secret-scan preflight regression tests; all token specimens are synthetic."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.secret_scan import MAX_FILE_BYTES, _safe_path_label, scan_file, scan_repository


class SecretScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")

    def git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def run_scan(self):
        output = io.StringIO()
        result = scan_repository(self.root, output=output)
        return result, output.getvalue()

    def test_only_tracked_files_are_scanned(self):
        self.put("tracked.py", "print('safe')")
        secret = "ghp" + "_" + "A" * 40
        self.put("untracked.py", secret)
        self.git("add", "tracked.py")
        status, result = self.run_scan()
        self.assertEqual(status, 0)
        self.assertIn("passed", result)
        self.assertNotIn(secret, result)

    def test_detects_tokens_without_printing_values(self):
        github = "ghp" + "_" + "A" * 40
        telegram = "12345678" + ":" + "z" * 35
        aws = "AKIA" + "A" * 16
        private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
        stripe = "sk_" + "live_" + "A" * 24
        openai = "sk" + "-" + "p" * 28
        slack = "xox" + "b-" + "A" * 24
        values = (github, telegram, aws, private_key_header, stripe, openai, slack)
        self.put("tracked.txt", "\n".join(values))
        self.git("add", "tracked.txt")
        status, result = self.run_scan()
        self.assertEqual(status, 1)
        for expected in (
            "github_access_token", "telegram_bot_token", "aws_access_key_id",
            "pem_private_key", "stripe_secret_key", "openai_api_key",
            "slack_secret_token",
        ):
            self.assertIn(expected, result)
        for value in values:
            self.assertNotIn(value, result)
        self.assertIn("values withheld", result)

    def test_tracked_env_file_refused_but_example_allowed(self):
        self.put(".env", "BOT_TOKEN=not-a-real-token")
        self.put(".env.example", "BOT_TOKEN=replace_with_your_bot_token")
        self.git("add", ".env", ".env.example")
        status, result = self.run_scan()
        self.assertEqual(status, 1)
        self.assertIn("tracked_private_file", result)
        self.assertNotIn("telegram_bot_token", result)
        self.assertEqual(scan_file(self.root, ".env.example"), ())

    def test_extra_filenames_are_private(self):
        self.put("service.pem", "placeholder")
        self.put("id_ed25519", "placeholder")
        self.assertEqual(scan_file(self.root, "service.pem"), ("tracked_private_file",))
        self.assertEqual(scan_file(self.root, "id_ed25519"), ("tracked_private_file",))

    def test_unusual_encoding_still_detects_ascii_secret(self):
        telegram = ("98765432" + ":" + "X" * 35).encode()
        self.put("input.dat", b"\xff\x00" + telegram)
        self.assertIn("telegram_bot_token", scan_file(self.root, "input.dat"))

    def test_oversize_text_fails_closed_and_large_media_skipped(self):
        self.put("large.txt", b"x" * (MAX_FILE_BYTES + 1))
        self.put("large.png", b"\x89PNG" + b"x" * MAX_FILE_BYTES)
        self.assertEqual(scan_file(self.root, "large.txt"), ("oversized_tracked_file",))
        self.assertEqual(scan_file(self.root, "large.png"), ())

    def test_does_not_follow_tracked_symlinks(self):
        self.put("private.txt", "private")
        (self.root / "linked.txt").symlink_to("private.txt")
        self.assertEqual(scan_file(self.root, "linked.txt"), ("tracked_symlink_requires_review",))

    def test_symlink_swap_after_lstat_fails_closed(self):
        path = self.put("tracked.txt", "ordinary text")
        self.put("private.txt", "private")
        original_open = os.open

        def replace_before_open(name, flags, *args, **kwargs):
            path.rename(self.root / "old.txt")
            path.symlink_to("private.txt")
            return original_open(name, flags, *args, **kwargs)

        with patch("tools.secret_scan.os.open", side_effect=replace_before_open):
            self.assertEqual(
                scan_file(self.root, "tracked.txt"),
                ("unreadable_tracked_file",),
            )

    def test_large_media_prefix_still_scans_for_tokens(self):
        specimen = ("12345678" + ":" + "z" * 35).encode()
        # A bot token must end at a token boundary, not directly adjoin the
        # filler's alphanumeric bytes.
        self.put("oversized.png", specimen + b"\n" + b"0" * MAX_FILE_BYTES)
        self.assertIn(
            "telegram_bot_token", scan_file(self.root, "oversized.png")
        )

    def test_token_without_terminal_boundary_is_not_a_false_positive(self):
        specimen = ("12345678" + ":" + "z" * 35).encode()
        self.put("not_a_token.txt", specimen + b"0")
        self.assertNotIn(
            "telegram_bot_token", scan_file(self.root, "not_a_token.txt")
        )

    def test_sensitive_token_in_filename_is_redacted(self):
        secret_name = "ghp" + "_" + "Z" * 40
        label = _safe_path_label(secret_name)
        self.assertTrue(label.startswith("<redacted-path:"))
        self.assertNotIn(secret_name, label)

    def test_missing_git_index_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            out = io.StringIO()
            code = scan_repository(Path(folder), output=out)
            self.assertEqual(code, 2)
            self.assertIn("git index unavailable", out.getvalue())


if __name__ == "__main__":
    unittest.main()
