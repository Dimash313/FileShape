"""Privacy-safe request label coverage without importing the API or secrets."""
import asyncio
import unittest

from api.observability import ROUTES, RequestTrace, route_label

JOB = "A" * 32


class RequestRouteLabelTests(unittest.TestCase):
    def test_every_implemented_static_route_uses_its_fixed_label(self):
        expected = {
            "/health": "health",
            "/ready": "ready",
            "/api/v1/session": "session",
            "/api/v1/convert": "convert",
            "/api/v1/images/pdf": "images_pdf",
            "/api/v1/capabilities": "capabilities",
            "/api/v1/queue": "queue",
            "/api/v1/usage": "usage",
            "/api/v1/jobs": "jobs_submit",
            "/api/v1/pdf/merge": "pdf_merge",
            "/api/v1/zip/create": "zip_create",
            "/internal/v1/access/check": "internal_access",
            "/internal/v1/operations/usage": "internal_usage",
            "/internal/v1/operations/reserve": "internal_reserve",
            "/internal/v1/operations/settle": "internal_settle",
            "/internal/v1/campaigns/join": "internal_campaign_join",
        }
        self.assertEqual(ROUTES, expected)
        for path, label in expected.items():
            with self.subTest(path=path):
                self.assertEqual(route_label(path), label)

    def test_job_route_shapes_cannot_emit_identifiers(self):
        for suffix, label in (
            ("", "job_status"),
            ("/result", "job_result"),
            ("/cancel", "job_cancel"),
            ("/retry", "job_retry"),
        ):
            path = f"/api/v1/jobs/{JOB}{suffix}"
            with self.subTest(path=path):
                self.assertEqual(route_label(path), label)
                self.assertNotIn(JOB, route_label(path))
                self.assertNotIn("/", route_label(path))

    def test_unknown_and_user_supplied_paths_are_generic(self):
        paths = (
            f"/api/v1/jobs/{JOB}/download",
            f"/api/v1/jobs/{JOB}/result/extra",
            "/api/v1/jobs/not-a-valid-id",
            "/api/v1/jobs/" + "X" * 33,
            "/api/v1/jobs/" + "X" * 31,
            "/api/v1/convert/secret-file.pdf",
            "/internal/v1/access/check/secret",
            "/api/v1/zip/extractions",
            "/sensitive-user-identifier",
            "",
            None,
            123,
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(route_label(path), "other")

    def test_request_id_and_status_are_preserved(self):
        # Existing response-header semantics remain intact.
        with self.assertLogs("fileshape.requests", level="INFO") as logs:
            async def app(scope, receive, send):
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})
            events = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(e):
                events.append(e)
            asyncio.run(RequestTrace(app)(
                {"type": "http", "path": f"/api/v1/jobs/{JOB}/result"}, receive, send,
            ))
        combined = "\n".join(logs.output)
        self.assertIn("route=job_result", combined)
        self.assertIn("status=200", combined)
        self.assertNotIn(JOB, combined)
        headers = dict(events[0]["headers"])
        self.assertRegex(headers[b"x-request-id"].decode(), r"^[a-f0-9]{16}$")
        self.assertEqual(events[-1]["body"], b"ok")

    def test_exception_logs_only_static_route_and_no_private_payload(self):
        secret = "private-token-or-filename"
        async def failing(scope, receive, send):
            raise RuntimeError(secret)
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(event):
            return None
        with self.assertLogs("fileshape.requests", level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, secret):
                asyncio.run(RequestTrace(failing)(
                    {"type": "http", "path": f"/api/v1/jobs/{JOB}/retry"}, receive, send,
                ))
        combined = "\n".join(logs.output)
        self.assertIn("route=job_retry", combined)
        self.assertNotIn(secret, combined)
        self.assertNotIn(JOB, combined)
        self.assertNotIn("Traceback", combined)


if __name__ == "__main__":
    unittest.main()
