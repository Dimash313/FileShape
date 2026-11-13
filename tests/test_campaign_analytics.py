"""Global campaign analytics: owner-only, privacy-preserving and pagination-independent."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from api import server
from api.durable_jobs import DurableJobStore


class CampaignAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DurableJobStore(Path(self.tmp.name) / "analytics.sqlite3")
        self.addCleanup(self.store.close)

    def test_counts_are_global_and_only_confirmed_events(self):
        for index in range(35):
            cid = self.store.create_campaign(
                actor_id=11, owner_id=11, chat_id=-100123456789 - index,
                mode="joins", target_joins=3, starts_at=100, ends_at=500, now=100)
            if index == 0:
                link = "https://t.me/+Abcdefgh12345678"
                self.store.bind_campaign_invite(
                    actor_id=11, owner_id=11, campaign_id=cid,
                    invite_link=link, now=101)
                self.store.change_campaign_state(
                    actor_id=11, owner_id=11, campaign_id=cid,
                    action="start", now=110)
                self.assertTrue(self.store.record_confirmed_join(
                    campaign_id=cid, observed_invite=link,
                    user_digest="a"*64, joined_at=111))
                self.assertFalse(self.store.record_confirmed_join(
                    campaign_id=cid, observed_invite=link,
                    user_digest="a"*64, joined_at=112))
        metrics = self.store.campaign_analytics(actor_id=11, owner_id=11, now=120)
        self.assertEqual(metrics["campaigns_total"], 35)
        self.assertEqual(metrics["campaigns_by_state"]["active"], 1)
        self.assertEqual(metrics["campaigns_by_state"]["draft"], 34)
        self.assertEqual(metrics["confirmed_joins_total"], 1)
        self.assertEqual(metrics["confirmed_joins_last_24h"], 1)
        self.assertEqual(metrics["pending_revocations"], 0)
        self.assertEqual(len(self.store.list_campaigns(
            actor_id=11, owner_id=11, limit=20)["items"]), 20)
        self.assertEqual(self.store.campaign_analytics(
            actor_id=11, owner_id=11, now=90000)["confirmed_joins_last_24h"], 0)
        with self.assertRaises(PermissionError):
            self.store.campaign_analytics(actor_id=12, owner_id=11)

    def test_pending_and_revoked_counts_are_distinct(self):
        cid = self.store.create_campaign(
            actor_id=11, owner_id=11, chat_id=-100123456789,
            mode="duration", starts_at=100, ends_at=200, now=100)
        link = "https://t.me/+Abcdefgh12345678"
        self.store.bind_campaign_invite(
            actor_id=11, owner_id=11, campaign_id=cid,
            invite_link=link, now=101)
        self.store.change_campaign_state(
            actor_id=11, owner_id=11, campaign_id=cid,
            action="stop", now=110)
        before = self.store.campaign_analytics(actor_id=11, owner_id=11, now=111)
        self.assertEqual((before["pending_revocations"], before["revoked_links"]), (1, 0))
        self.store.record_campaign_revoked(
            campaign_id=cid, chat_id=-100123456789, invite_link=link, now=112)
        after = self.store.campaign_analytics(actor_id=11, owner_id=11, now=113)
        self.assertEqual((after["pending_revocations"], after["revoked_links"]), (0, 1))


class AnalyticsAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DurableJobStore(Path(self.tmp.name) / "analytics.sqlite3")
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

    async def test_owner_only_analytics_endpoint(self):
        response = await self.client.get("/api/v1/owner/campaigns/analytics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["campaigns_total"], 0)
        server.api.dependency_overrides[server.authenticated_user] = lambda: 999
        response = await self.client.get("/api/v1/owner/campaigns/analytics")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
