"""Read-only usage status endpoint: signed identity, owner isolation, honest flags."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException

from api import server


class UsageStatusApiTests(unittest.TestCase):
    def test_snapshot_is_owner_scoped_and_not_claimed_enforced(self):
        seen = []
        def snapshot(user):
            seen.append(user)
            return {
                "plan": "free", "day_utc": "2026-11-14",
                "daily_limit": 10, "daily_used": 2,
                "daily_remaining": 8, "pack_remaining": 30,
                "pro_expires_at": None,
            }
        with patch.object(server, "jobs", SimpleNamespace(usage_snapshot=snapshot)), \
             patch.object(server, "enforce_rate_limit", new_callable=AsyncMock):
            response = asyncio.run(server.usage_status(123))
        import json
        body = json.loads(response.body)
        self.assertEqual(seen, [123])
        self.assertEqual(body["daily_remaining"], 8)
        self.assertEqual(body["pack_remaining"], 30)
        self.assertFalse(body["enforced"])
        self.assertFalse(body["purchases_enabled"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_unavailable_storage_fails_closed(self):
        with patch.object(server, "jobs", None), \
             patch.object(server, "enforce_rate_limit", new_callable=AsyncMock):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(server.usage_status(123))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_storage_failure_does_not_return_fake_balance(self):
        import sqlite3
        def fail(_):
            raise sqlite3.OperationalError("unavailable")
        with patch.object(server, "jobs", SimpleNamespace(usage_snapshot=fail)), \
             patch.object(server, "enforce_rate_limit", new_callable=AsyncMock):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(server.usage_status(123))
        self.assertEqual(ctx.exception.status_code, 503)
