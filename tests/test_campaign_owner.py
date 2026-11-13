"""Owner campaign API access, lifecycle, and Telegram invite cleanup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from api import server
from api.campaign_owner import owner_identity
from api.durable_jobs import DurableJobStore


class OwnerIdentityTests(unittest.TestCase):
    def test_owner_must_be_configured_and_match(self):
        for value in ("", "0", "-1", "abc", "999999999999999999999999"):
            with self.subTest(value=value), patch.dict("os.environ", {"FILESHAPE_OWNER_ID": value}):
                with self.assertRaises(HTTPException):
                    owner_identity(123)
        with patch.dict("os.environ", {"FILESHAPE_OWNER_ID": "123"}):
            self.assertEqual(owner_identity(123), 123)
            with self.assertRaises(HTTPException) as ctx:
                owner_identity(456)
            self.assertEqual(ctx.exception.status_code, 403)


class OwnerCampaignAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self.tmp.name) / "jobs.sqlite3")
        self.old_jobs, self.old_runtime = server.jobs, server.job_runtime
        server.jobs, server.job_runtime = self.store, object()
        server.api.dependency_overrides[server.authenticated_user] = lambda: 123
        self.env = patch.dict("os.environ", {"FILESHAPE_OWNER_ID": "123"})
        self.env.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.api), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()
        server.api.dependency_overrides.pop(server.authenticated_user, None)
        server.jobs, server.job_runtime = self.old_jobs, self.old_runtime
        self.store.close()
        self.tmp.cleanup()

    async def draft(self):
        return await self.client.post("/api/v1/owner/campaigns/drafts", json={
            "chat_id": -100123456789, "mode": "joins",
            "starts_at": 100, "ends_at": 9999999999, "target_joins": 2})

    async def test_owner_can_create_and_read_draft(self):
        response = await self.draft()
        self.assertEqual(response.status_code, 200, response.text)
        cid = response.json()["campaign_id"]
        snap = await self.client.get(f"/api/v1/owner/campaigns/{cid}")
        self.assertEqual(snap.status_code, 200, snap.text)
        self.assertEqual(snap.json()["confirmed_joins"], 0)
        self.assertEqual(snap.json()["state"], "draft")

    async def test_owner_can_list_and_page_campaigns_without_member_data(self):
        ids = []
        for _ in range(3):
            response = await self.draft()
            self.assertEqual(response.status_code, 200, response.text)
            ids.append(response.json()["campaign_id"])
        first = await self.client.get("/api/v1/owner/campaigns?offset=0&limit=2")
        second = await self.client.get("/api/v1/owner/campaigns?offset=2&limit=2")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual((first.json()["total"], second.json()["total"]), (3, 3))
        rows = first.json()["items"] + second.json()["items"]
        self.assertEqual({item["campaign_id"] for item in rows}, set(ids))
        self.assertEqual(len(rows), 3)
        for item in rows:
            self.assertEqual(item["confirmed_joins"], 0)
            self.assertEqual(item["invite_revocation"], "not_applicable")
            self.assertNotIn("user_digest", item)
            self.assertNotIn("member_id", item)
            self.assertNotIn("owner_id", item)

        for query in ("?limit=0", "?limit=31", "?offset=-1", "?offset=10001"):
            with self.subTest(query=query):
                self.assertEqual((await self.client.get(
                    "/api/v1/owner/campaigns" + query)).status_code, 422)

    async def test_list_is_owner_only_without_visibility_leaks(self):
        await self.draft()
        server.api.dependency_overrides[server.authenticated_user] = lambda: 456
        response = await self.client.get("/api/v1/owner/campaigns")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn("items", response.text)
        with self.assertRaises(PermissionError):
            self.store.list_campaigns(actor_id=456, owner_id=123)

    async def test_non_owner_cannot_create_or_read(self):
        cid = (await self.draft()).json()["campaign_id"]
        server.api.dependency_overrides[server.authenticated_user] = lambda: 456
        for method, path, kw in (
            ("post", "/api/v1/owner/campaigns/drafts", {"json": {}}),
            ("get", f"/api/v1/owner/campaigns/{cid}", {}),
            ("post", f"/api/v1/owner/campaigns/{cid}/invite", {}),
            ("post", f"/api/v1/owner/campaigns/{cid}/state", {"json": {"action": "stop"}}),
        ):
            response = await getattr(self.client, method)(path, **kw)
            self.assertEqual(response.status_code, 403, response.text)

    async def test_invalid_draft_and_illegal_transition(self):
        bad = await self.client.post("/api/v1/owner/campaigns/drafts", json={
            "chat_id": 123, "mode": "joins", "starts_at": 100,
            "ends_at": 200, "target_joins": 0})
        self.assertEqual(bad.status_code, 422)
        cid = (await self.draft()).json()["campaign_id"]
        response = await self.client.post(
            f"/api/v1/owner/campaigns/{cid}/state", json={"action": "start"})
        self.assertEqual(response.status_code, 409)
        response = await self.client.post(
            f"/api/v1/owner/campaigns/{cid}/state", json={"action": "stop"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "stopped")

    async def test_invite_creation_binds_actual_telegram_link(self):
        cid = (await self.draft()).json()["campaign_id"]
        bot = AsyncMock()
        bot.session.close = AsyncMock()
        link = "https://t.me/+Abcdefgh12345678"
        with patch("api.campaign_owner.Bot", return_value=bot), \
             patch("api.campaign_owner.get_settings", return_value=type("S", (), {"bot_token": "123456:TEST"})()), \
             patch("api.campaign_owner.create_campaign_invite", new=AsyncMock(return_value=link)):
            response = await self.client.post(f"/api/v1/owner/campaigns/{cid}/invite")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["invite_link"], link)
        snap = await self.client.get(f"/api/v1/owner/campaigns/{cid}")
        self.assertEqual(snap.json()["invite_link"], link)
        bot.session.close.assert_awaited_once()

    async def test_stopping_bound_campaign_attempts_immediate_revocation(self):
        cid = (await self.draft()).json()["campaign_id"]
        self.store.bind_campaign_invite(
            actor_id=123, owner_id=123, campaign_id=cid,
            invite_link="https://t.me/+Abcdefgh12345678")
        with patch("api.campaign_owner.dispatch_campaign_revocations",
                   new=AsyncMock(return_value=0)) as dispatcher:
            response = await self.client.post(
                f"/api/v1/owner/campaigns/{cid}/state",
                json={"action": "stop"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "stopped")
        self.assertEqual(response.json()["invite_revocation"], "pending")
        dispatcher.assert_awaited_once()

    async def test_telegram_failure_leaves_draft_unbound(self):
        cid = (await self.draft()).json()["campaign_id"]
        bot = AsyncMock()
        bot.session.close = AsyncMock()
        with patch("api.campaign_owner.Bot", return_value=bot), \
             patch("api.campaign_owner.get_settings", return_value=type("S", (), {"bot_token": "123456:TEST"})()), \
             patch("api.campaign_owner.create_campaign_invite",
                   new=AsyncMock(side_effect=RuntimeError("Telegram forbidden"))):
            response = await self.client.post(f"/api/v1/owner/campaigns/{cid}/invite")
        self.assertEqual(response.status_code, 502)
        snap = await self.client.get(f"/api/v1/owner/campaigns/{cid}")
        self.assertIsNone(snap.json()["invite_link"])
        bot.session.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
