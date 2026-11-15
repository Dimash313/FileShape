"""Contract tests for public, read-only conversion capability discovery."""
import asyncio
import json
import unittest

from fastapi.testclient import TestClient

from api import conversion_catalog, server
from api.capability_manifest import build_http_capabilities


class CapabilityManifestTests(unittest.TestCase):
    def test_manifest_is_versioned_deterministic_and_json_safe(self):
        first = build_http_capabilities()
        second = build_http_capabilities()
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["surface"], "http")
        self.assertEqual(first["route"], "/api/v1/convert")
        self.assertEqual(json.loads(json.dumps(first)), first)
        self.assertEqual(
            [item["kind"] for item in first["operations"]],
            sorted(conversion_catalog.SUPPORTED),
        )

    def test_only_actual_single_file_actions_are_advertised(self):
        manifest = build_http_capabilities()
        for item in manifest["operations"]:
            kind = item["kind"]
            self.assertEqual(item["actions"], sorted(conversion_catalog.SUPPORTED[kind]))
            self.assertEqual(item["input_extensions"], sorted(item["input_extensions"]))
            for extension in item["input_extensions"]:
                self.assertEqual(
                    conversion_catalog.file_kind("uploaded" + extension)[0], kind,
                )
        all_actions = {action for item in manifest["operations"] for action in item["actions"]}
        self.assertNotIn("audio:trim", all_actions)
        self.assertNotIn("video:extract_audio", all_actions)
        self.assertNotIn("docx:pdf", all_actions)
        self.assertNotIn("zip:extract", all_actions)

    def test_return_value_is_independent_of_mutable_internal_allowlist(self):
        manifest = build_http_capabilities()
        manifest["operations"][0]["actions"].append("not-a-real-action")
        manifest["operations"][0]["input_extensions"].append(".untrusted")
        rebuilt = build_http_capabilities()
        self.assertNotIn("not-a-real-action", str(rebuilt))
        self.assertNotIn(".untrusted", str(rebuilt))
        self.assertEqual(rebuilt["operations"][0]["kind"], "archive")

    def test_new_kind_requires_explicit_review_not_guesswork(self):
        try:
            conversion_catalog.SUPPORTED["unknown-kind"] = {"unknown:action"}
            with self.assertRaises(RuntimeError):
                build_http_capabilities()
        finally:
            conversion_catalog.SUPPORTED.pop("unknown-kind", None)

    def test_public_http_route_is_read_only_and_has_no_private_data(self):
        response = asyncio.run(server.public_capabilities())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = json.loads(response.body)
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["max_upload_bytes"], server.MAX_INPUT_BYTES)
        self.assertEqual(body["max_result_bytes"], server.MAX_RESULT_BYTES)
        self.assertNotIn("user_id", response.body.decode())
        self.assertNotIn("bot_token", response.body.decode())
        self.assertNotIn("billing", response.body.decode())
        self.assertTrue(any(
            route.path == "/api/v1/capabilities" and "GET" in route.methods
            for route in server.api.routes
        ))

    def test_http_route_does_not_require_telegram_login(self):
        # Inspecting available operations is not a conversion or a quota grant.
        # This does not weaken the authenticated processing admission paths.
        with TestClient(server.api) as client:
            result = client.get("/api/v1/capabilities")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["route"], "/api/v1/convert")
        self.assertEqual(result.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
