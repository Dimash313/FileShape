"""API access gate tests: no new admission on failed checks, no calls for Premium."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.access_policy import AccessDecision
from api import server


class ApiAccessGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_channels_allows_without_telegram(self):
        store = SimpleNamespace(premium_expiry=lambda _: None, list_required_channels=lambda: [])
        with patch.object(server, "jobs", store), patch.object(server, "Bot") as bot:
            self.assertEqual(await server.authorize_new_processing(11), 11)
            bot.assert_not_called()

    async def test_premium_allows_without_telegram(self):
        store = SimpleNamespace(premium_expiry=lambda _: 4102444800,
                                list_required_channels=lambda: [(-1001, 1000, None, True)])
        with patch.object(server, "jobs", store), patch.object(server, "Bot") as bot:
            self.assertEqual(await server.authorize_new_processing(11), 11)
            bot.assert_not_called()

    async def test_missing_membership_denies_new_processing(self):
        store = SimpleNamespace(premium_expiry=lambda _: None,
                                list_required_channels=lambda: [(-1001, 1000, None, True)])
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
        with patch.object(server, "jobs", store), patch.object(server, "Bot", return_value=bot), \\
             patch.object(server, "verify_memberships", new_callable=AsyncMock, return_value=AccessDecision.SUBSCRIPTION_REQUIRED):
            with self.assertRaises(HTTPException) as ctx:
                await server.authorize_new_processing(11)
            self.assertEqual(ctx.exception.status_code, 403)
            bot.session.close.assert_awaited_once()

    async def test_unavailable_denies_new_processing(self):
        store = SimpleNamespace(premium_expiry=lambda _: None,
                                list_required_channels=lambda: [(-1001, 1000, None, True)])
        bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
        with patch.object(server, "jobs", store), patch.object(server, "Bot", return_value=bot), \\
             patch.object(server, "verify_memberships", new_callable=AsyncMock, return_value=AccessDecision.VERIFICATION_UNAVAILABLE):
            with self.assertRaises(HTTPException) as ctx:
                await server.authorize_new_processing(11)
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_database_failure_fails_closed(self):
        import sqlite3
        store = SimpleNamespace(premium_expiry=lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("down")))
        with patch.object(server, "jobs", store):
            with self.assertRaises(HTTPException) as ctx:
                await server.authorize_new_processing(11)
            self.assertEqual(ctx.exception.status_code, 503)

    def test_only_admission_routes_have_gate(self):
        expected = {"/api/v1/jobs", "/api/v1/jobs/{job_id}/retry", "/api/v1/convert", "/api/v1/images/pdf"}
        for route in server.api.routes:
            if getattr(route, "path", None) not in expected or "POST" not in getattr(route, "methods", set()):
                continue
            self.assertIn(server.authorize_new_processing, [d.call for d in route.dependant.dependencies])
        for route in server.api.routes:
            if getattr(route, "path", None) in {"/api/v1/jobs/{job_id}", "/api/v1/jobs/{job_id}/result"}:
                self.assertNotIn(server.authorize_new_processing, [d.call for d in route.dependant.dependencies])


if __name__ == "__main__":
    unittest.main()
