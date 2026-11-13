import test from 'node:test';
import assert from 'node:assert/strict';
import { startJobPolling, isTerminal } from '../.test-dist/jobPolling.js';

const id = 'A'.repeat(32);
const status = state => ({ job_id: id, state, created_at: 100, updated_at: 101 });
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };
function fakeClock() {
  let now = 0;
  let sequence = 0;
  const timers = new Map();
  return {
    now: () => now,
    setTimeout(callback, delay) { const handle = ++sequence; timers.set(handle, { at: now + delay, callback }); return handle; },
    clearTimeout(handle) { timers.delete(handle); },
    count: () => timers.size,
    async advance(duration) {
      const target = now + duration;
      let iterations = 0;
      while (true) {
        assert.ok(iterations++ < 1000, 'timer loop must stay bounded');
        const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > target) break;
        now = next[1].at;
        timers.delete(next[0]);
        next[1].callback();
        await flush();
      }
      now = target;
      await flush();
    },
  };
}
function fixture(overrides = {}) {
  const clock = fakeClock();
  const states = [];
  const notices = [];
  const stops = [];
  let available = true;
  const options = {
    jobId: id, clock, request: async () => status('queued'),
    available: () => available,
    onStatus: value => states.push(value.state),
    onNotice: value => notices.push(value),
    onStop: value => stops.push(value),
    ...overrides,
  };
  const control = startJobPolling(options);
  return { clock, states, notices, stops, control, available: value => { available = value; control.availabilityChanged(); } };
}

test('confirmed queued, processing and completed stop all polling', async () => {
  const sequence = ['queued', 'processing', 'completed'];
  let requests = 0;
  const f = fixture({ request: async () => { requests += 1; return status(sequence.shift()); } });
  await flush();
  assert.deepEqual(f.states, ['queued']);
  await f.clock.advance(9999);
  assert.equal(requests, 1);
  await f.clock.advance(1);
  assert.deepEqual(f.states, ['queued', 'processing']);
  await f.clock.advance(10_000);
  assert.deepEqual(f.states, ['queued', 'processing', 'completed']);
  await f.clock.advance(3_600_000);
  f.control.refresh();
  assert.equal(requests, 3);
  assert.equal(f.clock.count(), 0);
  assert.deepEqual(f.stops, ['terminal']);
});

test('failed and cancelled are terminal server states', async () => {
  assert.equal(isTerminal('queued'), false);
  assert.equal(isTerminal('processing'), false);
  for (const terminal of ['failed', 'cancelled']) {
    const f = fixture({ request: async () => status(terminal) });
    await flush();
    await f.clock.advance(60_000);
    assert.deepEqual(f.states, [terminal]);
    assert.equal(f.clock.count(), 0);
  }
});

test('hidden/offline aborts and stale responses cannot update or overlap', async () => {
  const calls = [];
  const f = fixture({ request: signal => new Promise(resolve => calls.push({ signal, resolve })) });
  await flush();
  assert.equal(calls.length, 1);
  f.available(false);
  assert.equal(calls[0].signal.aborted, true);
  f.available(true);
  await f.clock.advance(15_000);
  assert.equal(calls.length, 1, 'an unresolved aborted request still counts as in-flight');
  calls[0].resolve(status('completed'));
  await flush();
  assert.deepEqual(f.states, [], 'stale completed response must not apply');
  assert.equal(calls.length, 2);
  calls[1].resolve(status('processing'));
  await flush();
  assert.deepEqual(f.states, ['processing']);
  f.control.dispose();
});

test('resume and repeated manual refresh respect the ten-second floor', async () => {
  let requests = 0;
  const f = fixture({ request: async () => { requests += 1; return status('queued'); } });
  await flush();
  for (let i = 0; i < 10; i += 1) { f.available(false); f.available(true); f.control.refresh(); }
  await f.clock.advance(9999);
  assert.equal(requests, 1);
  await f.clock.advance(1);
  assert.equal(requests, 2);
  f.control.dispose();
});

test('initially unavailable makes no requests until availability resumes', async () => {
  let available = false;
  let requests = 0;
  const f = fixture({ available: () => available, request: async () => { requests += 1; return status('queued'); } });
  await f.clock.advance(20_000);
  assert.equal(requests, 0);
  available = true;
  f.control.availabilityChanged();
  await flush();
  assert.equal(requests, 1);
  f.control.dispose();
});

test('transient failure backs off and never invents a failed state', async () => {
  let requests = 0;
  const f = fixture({ request: async () => {
    requests += 1;
    if (requests < 3) throw new Error('offline');
    return status('processing');
  } });
  await flush();
  assert.deepEqual(f.states, []);
  await f.clock.advance(19_999);
  assert.equal(requests, 1);
  await f.clock.advance(1);
  assert.equal(requests, 2);
  await f.clock.advance(39_999);
  assert.equal(requests, 2);
  await f.clock.advance(1);
  assert.equal(requests, 3);
  assert.deepEqual(f.states, ['processing']);
  f.control.dispose();
});

test('attempt budget stops, and explicit refresh starts a new bounded budget', async () => {
  let requests = 0;
  const f = fixture({ maxAttempts: 2, request: async () => { requests += 1; return status('processing'); } });
  await flush();
  await f.clock.advance(10_000);
  assert.equal(requests, 2);
  assert.deepEqual(f.stops, ['limit']);
  f.control.refresh();
  for (let i = 0; i < 5; i += 1) f.control.refresh();
  await f.clock.advance(9999);
  assert.equal(requests, 2);
  await f.clock.advance(1);
  assert.equal(requests, 3);
  f.control.dispose();
});

test('wall-clock budget also bounds hidden or hanging requests', async () => {
  let signal;
  const f = fixture({ budgetMs: 15_000, request: requestSignal => { signal = requestSignal; return new Promise(() => {}); } });
  await f.clock.advance(15_000);
  assert.equal(signal.aborted, true);
  assert.deepEqual(f.stops, ['limit']);
  assert.equal(f.clock.count(), 0);
  f.control.dispose();
});

test('terminal request errors stop instead of repeated unauthorized calls', async () => {
  let requests = 0;
  const f = fixture({ request: async () => { requests += 1; throw Object.assign(new Error('Сессия устарела'), { terminal: true }); } });
  await flush();
  await f.clock.advance(3_600_000);
  f.control.refresh();
  assert.equal(requests, 1);
  assert.deepEqual(f.states, []);
  assert.deepEqual(f.stops, ['terminal-error']);
  assert.equal(f.notices.at(-1), 'Сессия устарела');
});

test('response for a different job is ignored', async () => {
  const f = fixture({ request: async () => ({ ...status('completed'), job_id: 'B'.repeat(32) }) });
  await flush();
  assert.deepEqual(f.states, []);
  assert.match(f.notices.at(-1), /Не удалось/);
  f.control.dispose();
});

test('dispose aborts requests, removes timers and ignores future results', async () => {
  let signal;
  let resolve;
  const f = fixture({ request: requestSignal => { signal = requestSignal; return new Promise(done => { resolve = done; }); } });
  f.control.dispose();
  assert.equal(signal.aborted, true);
  resolve(status('completed'));
  await flush();
  await f.clock.advance(60_000);
  f.control.refresh();
  assert.deepEqual(f.states, []);
  assert.equal(f.clock.count(), 0);
});

test('unsafe polling limits cannot disable the request floor or bounds', () => {
  for (const overrides of [{ interval: 9999 }, { interval: 60_001 }, { budgetMs: Infinity }, { budgetMs: 1_800_001 }, { maxAttempts: 181 }, { maxAttempts: 0 }]) {
    assert.throws(() => fixture(overrides), RangeError);
  }
});
