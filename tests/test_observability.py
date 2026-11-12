"""Request correlation is stable per response and excludes private data."""
import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import api


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api)
        self.addCleanup(self.client.close)

    def test_request_id_is_hex_and_unique(self):
        first = self.client.get("/health")
        second = self.client.get("/health")
        self.assertEqual(first.status_code, 200)
        for response in (first, second):
            self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{16}$")
        self.assertNotEqual(first.headers["x-request-id"], second.headers["x-request-id"])

    def test_log_does_not_include_private_request_details(self):
        secret = "private-token-should-not-be-logged"
        with patch.dict(os.environ, {"BOT_TOKEN": "987654:testing-token-only"}):
            with self.assertLogs("fileshape.requests", level="INFO") as captured:
                response = self.client.get(
                    "/api/v1/session",
                    headers={"X-Telegram-Init-Data": secret},
                )
        self.assertEqual(response.status_code, 401)
        combined = "\n".join(captured.output)
        self.assertIn("route=session", combined)
        self.assertIn("status=401", combined)
        self.assertNotIn(secret, combined)
        self.assertNotIn("/api/v1/session", combined)

    def test_unknown_path_has_generic_label(self):
        with self.assertLogs("fileshape.requests", level="INFO") as captured:
            response = self.client.get("/private-name-123")
        self.assertEqual(response.status_code, 404)
        self.assertIn("route=other", "\n".join(captured.output))
        self.assertNotIn("private-name-123", "\n".join(captured.output))

    def test_oversized_upload_receives_request_id(self):
        response = self.client.post(
            "/api/v1/convert",
            headers={"content-length": "999999999"},
            content=b"x",
        )
        self.assertEqual(response.status_code, 413)
        self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{16}$")


if __name__ == "__main__":
    unittest.main()
