"""Static checks for container configuration; no Docker daemon required."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_dockerfile_is_non_root(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("USER fileshape", dockerfile)
        self.assertIn("ffmpeg", dockerfile)
        self.assertIn('CMD ["python", "main.py"]', dockerfile)

    def test_compose_has_restart_and_resource_limits(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("mem_limit:", compose)
        self.assertIn("pids_limit:", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("- ALL", compose)
        self.assertIn("env_file:", compose)

    def test_secret_files_are_excluded(self):
        ignored = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertIn(".env", ignored)
        self.assertIn("*.sqlite3", ignored)
        self.assertIn(".git", ignored)


if __name__ == "__main__":
    unittest.main()
