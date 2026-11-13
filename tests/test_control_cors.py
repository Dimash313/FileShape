"""Idempotency headers must work for the configured exact Mini App origin."""
import os
import subprocess
import sys
import unittest


class ControlCorsTests(unittest.TestCase):
    def test_preflight_allows_idempotency_header_only_for_configured_origin(self):
        code = '''
from fastapi.testclient import TestClient
from api.server import api
with TestClient(api) as client:
    headers = {
        "origin": "https://miniapp.fileshape.test",
        "access-control-request-method": "POST",
        "access-control-request-headers": "X-Telegram-Init-Data,Idempotency-Key,Content-Type",
    }
    response = client.options("/api/v1/jobs", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == headers["origin"]
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
    headers["origin"] = "https://other.fileshape.test"
    response = client.options("/api/v1/jobs", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
'''
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "MINIAPP_ORIGIN": "https://miniapp.fileshape.test", "FILESHAPE_STATE_DIR": directory}
            child = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr.decode('utf-8', errors='replace'))
