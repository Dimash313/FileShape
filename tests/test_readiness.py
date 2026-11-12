"""Readiness checks must fail closed without exposing infrastructure details."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.readiness import readiness_status
from api import server
from api.server import api


class ReadinessTests(unittest.TestCase):
    def test_all_dependencies_available(self):
        with patch("api.readiness.shutil.which", return_value="/usr/bin/program"):
            result = readiness_status()
        self.assertEqual(result["status"], "ready")
        self.assertTrue(all(result["checks"].values()))

    def test_missing_ffmpeg_returns_unavailable(self):
        def locate(name):
            return None if name == "ffmpeg" else "/usr/bin/ffprobe"
        with patch("api.readiness.shutil.which", side_effect=locate):
            result = readiness_status()
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["checks"]["ffmpeg"])

    def test_unwritable_temp_storage(self):
        with patch("api.readiness.shutil.which", return_value="/usr/bin/program"):
            with patch("api.readiness.tempfile.TemporaryDirectory", side_effect=OSError("no space")):
                result = readiness_status()
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["checks"]["temporary_storage"])

    def test_queue_reopens_after_clean_restart(self):
        with TestClient(api):
            self.assertFalse(server.admission.closing)
        self.assertTrue(server.admission.closing)
        with TestClient(api):
            self.assertFalse(server.admission.closing)
        self.assertTrue(server.admission.closing)

    def test_http_readiness_status_and_liveness(self):
        with TestClient(api) as client:
            with patch("api.server.readiness_status", return_value={"status": "unavailable", "checks": {"ffmpeg": False}}):
                response = client.get("/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(client.get("/health").status_code, 200)
            with patch("api.server.readiness_status", return_value={"status": "ready", "checks": {"ffmpeg": True}}):
                self.assertEqual(client.get("/ready").status_code, 200)


if __name__ == "__main__":
    unittest.main()
