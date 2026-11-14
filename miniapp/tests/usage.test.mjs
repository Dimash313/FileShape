import test from 'node:test';
import assert from 'node:assert/strict';

import { validateUsageSnapshot, nextUtcReset } from '../.test-dist/usage.js';

const free = {
  plan: 'free', day_utc: '2026-11-14', daily_limit: 10, daily_used: 2,
  daily_remaining: 8, pack_remaining: 30, pro_expires_at: null,
  enforced: true, purchases_enabled: false,
};

test('verified profile uses only validated account fields and computes UTC reset', () => {
  assert.deepEqual(validateUsageSnapshot({ ...free, owner_id: 112233, filename: 'private.txt' }), free);
  assert.match(nextUtcReset('2026-11-14'), /15\.11.*00:00 UTC/);
});

test('real Pro expiry is required and no fake Pro date is accepted', () => {
  const pro = {
    ...free, plan: 'pro', daily_limit: 100, daily_used: 87,
    daily_remaining: 13, pro_expires_at: 1794699200,
  };
  assert.deepEqual(validateUsageSnapshot(pro), pro);
  assert.throws(() => validateUsageSnapshot({ ...pro, pro_expires_at: null }));
  assert.throws(() => validateUsageSnapshot({ ...free, pro_expires_at: 1794699200 }));
  assert.throws(() => validateUsageSnapshot({ ...pro, pro_expires_at: Infinity }));
});

test('reject fabricated, inconsistent or invalid server balances', () => {
  for (const value of [
    null, [], {}, { ...free, plan: 'premium' },
    { ...free, daily_used: -1 },
    { ...free, daily_used: 4 },
    { ...free, daily_remaining: '8' },
    { ...free, daily_remaining: 80 },
    { ...free, pack_remaining: -1 },
    { ...free, pack_remaining: 10001 },
    { ...free, pack_remaining: NaN },
    { ...free, daily_used: 1.5 },
    { ...free, day_utc: '2026-02-30' },
    { ...free, day_utc: '2026-11-14T12:00:00Z' },
    { ...free, enforced: 'yes' },
    { ...free, purchases_enabled: 1 },
    { ...free, daily_limit: 100 },
  ]) assert.throws(() => validateUsageSnapshot(value));
});

test('free plan after Pro expiry may have more used operations than free quota', () => {
  const state = { ...free, daily_used: 85, daily_remaining: 0 };
  assert.deepEqual(validateUsageSnapshot(state), state);
});
