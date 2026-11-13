"""Signed bot metering client cannot bypass the API or expose its token."""
import os
import unittest
from unittest.mock import patch

from api.internal_access import ReplayGuard
from services.bot_operations import (
    reserve_bot_operation, settle_bot_operation,
    BotOperationQuotaExceeded, BotOperationUnavailable,
)

TOKEN = "123456:TEST"
JOB_ID = "AbCD" * 8
URL = "http://api:8000/internal/v1/operations"


class AsyncScope:
    def __init__(self, result):
        self.result = result

    async def __aenter__(self):
        return self.result

    async def __aexit__(self, *args):
        return False


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data

    async def json(self, **kwargs):
        return self.data


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.url = None
        self.payload = None
        self.headers = None
        self.redirects = None

    def post(self, url, *, json, headers, allow_redirects):
        self.url, self.payload, self.headers, self.redirects = url, json, headers, allow_redirects
        return AsyncScope(self.response)


class BotOperationClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_uses_scoped_signature_without_bot_token(self):
        session = FakeSession(FakeResponse(data={"job_id": JOB_ID, "state": "processing", "created": True}))
        with (
            patch.dict(os.environ, {"FILESHAPE_OPERATION_GATE_URL": URL}),
            patch("services.bot_operations.aiohttp.ClientSession", return_value=AsyncScope(session)),
        ):
            self.assertEqual(await reserve_bot_operation(11, TOKEN), JOB_ID)
        self.assertEqual(session.url, URL + "/reserve")
        self.assertFalse(session.redirects)
        self.assertNotIn(TOKEN, str(session.headers))
        request_id = session.payload["request_id"]
        self.assertRegex(request_id, r"^[a-f0-9]{32}$")
        ReplayGuard().verify(
            token=TOKEN, user=session.headers["X-FileShape-User"],
            timestamp=session.headers["X-FileShape-Time"],
            nonce=session.headers["X-FileShape-Nonce"],
            signature=session.headers["X-FileShape-Signature"],
            scope="reserve:" + request_id,
            now=int(session.headers["X-FileShape-Time"]),
        )

    async def test_settle_uses_case_sensitive_opaque_job_id_in_signature(self):
        session = FakeSession(FakeResponse(data={"job_id": JOB_ID, "state": "completed"}))
        with (
            patch.dict(os.environ, {"FILESHAPE_OPERATION_GATE_URL": URL}),
            patch("services.bot_operations.aiohttp.ClientSession", return_value=AsyncScope(session)),
        ):
            await settle_bot_operation(11, TOKEN, JOB_ID, True)
        self.assertEqual(session.url, URL + "/settle")
        self.assertEqual(session.payload, {"job_id": JOB_ID, "success": True})
        ReplayGuard().verify(
            token=TOKEN, user=session.headers["X-FileShape-User"],
            timestamp=session.headers["X-FileShape-Time"],
            nonce=session.headers["X-FileShape-Nonce"],
            signature=session.headers["X-FileShape-Signature"],
            scope="settle:" + JOB_ID + ":1",
            now=int(session.headers["X-FileShape-Time"]),
        )

    async def test_quota_http_error_and_bad_response_fail_closed(self):
        for response, exception in (
            (FakeResponse(status=429), BotOperationQuotaExceeded),
            (FakeResponse(status=503), BotOperationUnavailable),
            (FakeResponse(status=302), BotOperationUnavailable),
            (FakeResponse(status=200, data={"state": "processing"}), BotOperationUnavailable),
        ):
            session = FakeSession(response)
            with (
                self.subTest(status=response.status),
                patch.dict(os.environ, {"FILESHAPE_OPERATION_GATE_URL": URL}),
                patch("services.bot_operations.aiohttp.ClientSession", return_value=AsyncScope(session)),
            ):
                with self.assertRaises(exception):
                    await reserve_bot_operation(11, TOKEN)

    async def test_no_internal_gate_never_approves_unaudited_operations(self):
        with patch.dict(os.environ, {"FILESHAPE_OPERATION_GATE_URL": "", "FILESHAPE_ACCESS_GATE_URL": ""}):
            with self.assertRaises(BotOperationUnavailable):
                await reserve_bot_operation(11, TOKEN)


if __name__ == "__main__":
    unittest.main()
