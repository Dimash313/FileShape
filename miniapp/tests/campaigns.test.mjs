import test from 'node:test';
import assert from 'node:assert/strict';

const campaignId = 'A'.repeat(32);
let moduleSequence = 0;
const load = () => import(`../.test-dist/campaignsApi.js?case=${++moduleSequence}`);

function environment() {
  globalThis.window = { Telegram: { WebApp: { initData: 'signed-owner-session' } } };
}
const sample = (changes = {}) => ({
  campaign_id: campaignId, chat_id: -100123456789,
  mode: 'joins', target_joins: 10,
  starts_at: 1794570000, ends_at: 1794656400,
  state: 'active', confirmed_joins: 3,
  invite_link: 'https://t.me/+Abcdefgh12345678',
  invite_revocation: 'not_due', revoke_attempts: 0,
  revoked_at: null, created_at: 1794570000, ...changes,
});

test('owner-only listing sends signed Telegram session, no-store and bounded page', async () => {
  environment();
  const api = await load();
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return Response.json({ items: [sample()], total: 1 });
  };
  const result = await api.listCampaigns();
  assert.equal(result.total, 1);
  assert.equal(result.items[0].confirmed_joins, 3);
  assert.equal(requests[0].url, '/api/v1/owner/campaigns?offset=0&limit=20');
  assert.equal(requests[0].options.headers['X-Telegram-Init-Data'], 'signed-owner-session');
  assert.equal(requests[0].options.cache, 'no-store');
  assert.equal(requests[0].options.redirect, 'error');
});

test('invalid results never display fictional subscriber metrics', async () => {
  environment();
  const api = await load();
  for (const bad of [
    sample({ confirmed_joins: '1000' }),
    sample({ confirmed_joins: -1 }),
    sample({ campaign_id: '../bad' }),
    sample({ invite_revocation: 'fake-revoked' }),
    sample({ invite_link: 'https://fake.example/a' }),
    sample({ target_joins: null }),
  ]) {
    assert.throws(() => api.validateCampaign(bad));
  }
  assert.throws(() => api.validateCampaignPage({ items: [sample()], total: 0 }, 20));
  assert.throws(() => api.validateCampaignPage({ items: [sample(), sample()], total: 2 }, 1));
});

test('nonowner 403 is explicit; no fallback or unauthenticated requests', async () => {
  environment();
  const api = await load();
  let called = 0;
  globalThis.fetch = async () => { called += 1; return Response.json({ detail: 'forbidden' }, { status: 403 }); };
  await assert.rejects(api.listCampaigns(), error => error instanceof api.CampaignApiError && error.status === 403);
  assert.equal(called, 1);
  window.Telegram.WebApp.initData = '';
  await assert.rejects(api.listCampaigns(), error => error.status === 401);
  assert.equal(called, 1);
});

test('mutations carry signed body and only accept confirmed IDs and states', async () => {
  environment();
  const api = await load();
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith('/drafts')) return Response.json({ campaign_id: campaignId, state: 'draft' });
    if (url.endsWith('/invite')) return Response.json({ campaign_id: campaignId, invite_link: 'https://t.me/+Abcdefgh12345678' });
    return Response.json({ campaign_id: campaignId, state: 'paused' });
  };
  assert.equal(await api.createCampaign({
    chat_id: -100123456789, mode: 'joins', starts_at: 1794570000,
    ends_at: 1794656400, target_joins: 10,
  }), campaignId);
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[0].options.headers['Content-Type'], 'application/json');
  assert.equal(JSON.parse(requests[0].options.body).target_joins, 10);
  assert.equal(await api.createCampaignInvite(campaignId), 'https://t.me/+Abcdefgh12345678');
  assert.equal(requests[1].url, `/api/v1/owner/campaigns/${campaignId}/invite`);
  assert.equal(await api.changeCampaignState(campaignId, 'pause'), 'paused');
  assert.equal(JSON.parse(requests[2].options.body).action, 'pause');
});

test('invalid commands, campaigns and pagination make no request', async () => {
  environment();
  const api = await load();
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw Error('unexpected'); };
  await assert.rejects(api.listCampaigns(-1, 20));
  await assert.rejects(api.listCampaigns(0, 31));
  await assert.rejects(api.createCampaignInvite('../secret'));
  await assert.rejects(api.changeCampaignState(campaignId, 'delete'));
  await assert.rejects(api.createCampaign({
    chat_id: 123, mode: 'joins', starts_at: 1, ends_at: 2, target_joins: 1,
  }));
  assert.equal(calls, 0);
});

test('failed or malformed mutation never becomes a confirmed success', async () => {
  environment();
  const api = await load();
  globalThis.fetch = async () => Response.json(
    { campaign_id: campaignId, invite_link: 'https://example.com/fake' },
  );
  await assert.rejects(api.createCampaignInvite(campaignId));
  globalThis.fetch = async () => Response.json(
    { campaign_id: campaignId, state: 'completed' }, { status: 503 },
  );
  await assert.rejects(api.changeCampaignState(campaignId, 'start'), error => error.status === 503);
});
