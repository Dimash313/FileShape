"""No unauthenticated bot-to-API access, replay or user spoofing."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import httpx

from api.internal_access import ReplayGuard, sign_access_request
from api import server


TOKEN = "123456:TEST"
NOW = 1794570000


class InternalAccessPrimitiveTests(unittest.TestCase):
    def test_signed_valid_replay_spoof_and_expiry(self):
        guard = ReplayGuard()
        nonce = "0" * 32
        sig = sign_access_request(TOKEN, 11, NOW, nonce)
        params = dict(token=TOKEN, user="11", timestamp=str(NOW),
                      nonce=nonce, signature=sig, now=NOW)
        self.assertEqual(guard.verify(**params), 11)
        with self.assertRaises(ValueError):
            guard.verify(**params)
        for altered in (
            dict(user="12"), dict(token="wrong:token"),
            dict(signature="0" * 64), dict(timestamp=str(NOW - 40)),
            dict(timestamp=str(NOW + 40)), dict(nonce="1" * 32),
        ):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                ReplayGuard().verify(**(params | altered))

    def test_invalid_identity_and_nonce_rejected(self):
        for uid in (0, -1, True, 2**63):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                sign_access_request(TOKEN, uid, NOW, "a" * 32)
        for val in ("not-hex", "a" * 31, "g" * 32):
            with self.subTest(nonce=val), self.assertRaises(ValueError):
                sign_access_request(TOKEN, 11, NOW, val)

    def test_nonce_budget_fails_closed(self):
        with patch("api.internal_access.MAX_NONCES", 1):
            guard = ReplayGuard()
            for nonce, expected in (("a" * 32, True), ("b" * 32, False)):
                payload = dict(token=TOKEN, user="11", timestamp=str(NOW),
                               nonce=nonce, signature=sign_access_request(TOKEN, 11, NOW, nonce), now=NOW)
                if expected:
                    self.assertEqual(guard.verify(**payload), 11)
                else:
                    with self.assertRaises(ValueError):
                        guard.verify(**payload)


class InternalAccessEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guard = ReplayGuard()
        self.mock_jobs = SimpleNamespace()
        self.auth = AsyncMock(return_value=11)
        self.settings = SimpleNamespace(bot_token=TOKEN)
        self.patches = [
            patch.object(server, "internal_access_replay", self.guard),
            patch.object(server, "job_runtime", object()),
            patch.object(server, "jobs", self.mock_jobs),
            patch.object(server, "authorize_new_processing", self.auth),
            patch.object(server, "get_settings", return_value=self.settings),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.api),
            base_url="http://test.internal",
        )
        self.addAsyncCleanup(self.client.aclose)

    def headers(self, user=11, nonce=None, issued=NOW, token=TOKEN):
        if nonce is None:
            import secrets
            nonce = secrets.token_hex(16)
        return {
            "X-FileShape-User": str(user),
            "X-FileShape-Time": str(issued),
            "X-FileShape-Nonce": nonce,
            "X-FileShape-Signature": sign_access_request(token, user, issued, nonce),
        }

    async def test_unsigned_bad_signature_and_replay_are_rejected(self):
        with patch("api.internal_access.time.time", return_value=NOW):
            r = await self.client.post("/internal/v1/access/check")
            self.assertEqual(r.status_code, 401)
            headers = self.headers()
            r = await self.client.post("/internal/v1/access/check", headers=headers)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"decision": "allowed"})
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            r = await self.client.post("/internal/v1/access/check", headers=headers)
            self.assertEqual(r.status_code, 401)
            spoof = self.headers()
            spoof["X-FileShape-User"] = "12"
            self.assertEqual((await self.client.post("/internal/v1/access/check", headers=spoof)).status_code, 401)
            expired = self.headers(issued=NOW - 31)
            self.assertEqual((await self.client.post("/internal/v1/access/check", headers=expired)).status_code, 401)
            self.auth.assert_awaited_once_with(11)

    async def test_user_denial_vs_failure_and_no_token_echo(self):
        with patch("api.internal_access.time.time", return_value=NOW):
            self.auth.side_effect = HTTPException(status_code=403, detail="channels")
            r = await self.client.post("/internal/v1/access/check", headers=self.headers())
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"decision": "subscription_required"})
            self.auth.side_effect = HTTPException(status_code=503, detail="unavailable")
            r = await self.client.post("/internal/v1/access/check", headers=self.headers())
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"decision": "verification_unavailable"})
            self.assertNotIn(TOKEN, r.text)

    async def test_runtime_unavailable_fails_closed(self):
        with patch.object(server, "job_runtime", None):
            r = await self.client.post("/internal/v1/access/check", headers=self.headers())
            self.assertEqual(r.status_code, 503)
            self.auth.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
