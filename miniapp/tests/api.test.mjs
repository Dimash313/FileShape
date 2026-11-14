import test from 'node:test';
import assert from 'node:assert/strict';

const jobId = 'A'.repeat(32);
const status = state => ({ job_id: jobId, state, created_at: Math.floor(Date.now() / 1000) - 1, updated_at: Math.floor(Date.now() / 1000) });
let moduleSequence = 0;
const load = () => import(`../.test-dist/api.js?test=${++moduleSequence}`);
function environment() {
  globalThis.window = { Telegram: { WebApp: { initData: 'signed-launch-data' } }, setTimeout, clearTimeout };
}

test('verified owner comes from signed session and rejects truthy non-boolean ok', async () => {
  environment(); const api = await load();
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return Response.json({ ok: true, user_id: 11 });
  };
  assert.equal(await api.getVerifiedOwner(), 11);
  assert.equal(requests[0].url, '/api/v1/session');
  assert.equal(requests[0].options.headers['X-Telegram-Init-Data'], 'signed-launch-data');
  assert.equal(requests[0].options.cache, 'no-store');
  globalThis.fetch = async () => Response.json({ ok: 'yes', user_id: 11 });
  await assert.rejects(api.getVerifiedOwner(), /сессия/);
});

test('missing Telegram data makes no API request', async () => {
  environment(); window.Telegram.WebApp.initData = ''; const api = await load();
  let called = false; globalThis.fetch = async () => { called = true; throw Error('unexpected'); };
  await assert.rejects(api.getVerifiedOwner());
  await assert.rejects(api.getJobStatus(jobId));
  await assert.rejects(api.getBackgroundResult(jobId, 'txt:docx'));
  assert.equal(called, false);
});

test('status reads are globally throttled across different IDs and manual callers', async () => {
  environment(); const api = await load(); let calls = 0;
  globalThis.fetch = async () => { calls += 1; return Response.json(status('queued')); };
  assert.equal((await api.getJobStatus(jobId)).state, 'queued');
  await assert.rejects(api.getJobStatus('B'.repeat(32)), error => error.status === 429);
  assert.equal(calls, 1);
});

test('terminal status errors are distinguishable from transient errors', async () => {
  environment(); let api = await load();
  globalThis.fetch = async () => Response.json({ detail: 'missing' }, { status: 404 });
  await assert.rejects(api.getJobStatus(jobId), error => error.status === 404 && error.terminal);
  api = await load(); globalThis.fetch = async () => Response.json({}, { status: 503 });
  await assert.rejects(api.getJobStatus(jobId), error => error.status === 503 && !error.terminal);
});

test('malformed or mismatched status cannot replace a confirmed job', async () => {
  environment(); const api = await load();
  assert.throws(() => api.validateJobStatus({ ...status('queued'), job_id: 'x' }));
  assert.throws(() => api.validateJobStatus(status('imaginary-progress')));
  assert.throws(() => api.validateJobStatus({ ...status('queued'), updated_at: NaN }));
  assert.throws(() => api.validateJobStatus(status('completed'), 'B'.repeat(32)));
  assert.deepEqual(Object.keys(api.validateJobStatus({ ...status('completed'), filename: 'private.txt' })).sort(), ['created_at', 'job_id', 'state', 'updated_at']);
});

test('background creation accepts only HTTP202 and reports actual upload bytes then validation', async () => {
  environment(); const api = await load(); const progress = []; let request;
  globalThis.XMLHttpRequest = class {
    upload = {};
    status = 202;
    open(method, url) { request = { method, url, headers: {} }; }
    setRequestHeader(name, value) { request.headers[name] = value; }
    getResponseHeader(name) { return name === 'Content-Type' ? 'application/json' : null; }
    send(form) {
      request.form = form;
      this.upload.onprogress({ lengthComputable: true, loaded: 4, total: 8 });
      this.upload.onload();
      this.response = new Blob([JSON.stringify(status('queued'))], { type: 'application/json' });
      queueMicrotask(() => this.onload());
    }
  };
  const result = await api.createBackgroundJob(new File(['hello'], 'private.txt'), 'txt:docx', '', value => progress.push(value));
  assert.equal(result.job_id, jobId);
  assert.equal(request.url, '/api/v1/jobs');
  assert.equal(request.headers['X-Telegram-Init-Data'], 'signed-launch-data');
  assert.deepEqual(progress, [{ stage: 'upload', percent: null }, { stage: 'upload', percent: 50 }, { stage: 'validation', percent: null }]);
});

test('unexpected HTTP200 does not become an accepted background job', async () => {
  environment(); const api = await load();
  globalThis.XMLHttpRequest = class {
    upload = {}; status = 200;
    open() {} setRequestHeader() {}
    send() { this.response = new Blob([JSON.stringify(status('queued'))]); queueMicrotask(() => this.onload()); }
  };
  await assert.rejects(api.createBackgroundJob(new File(['x'], 'x.txt'), 'txt:docx', ''), error => error.status === 200);
});

test('result requests authenticate headers, handle JSON info and never persist a file', async () => {
  environment(); const api = await load(); let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return Response.json({ info: { lines: 2, characters: 4 } });
  };
  const result = await api.getBackgroundResult(jobId, 'txt:info');
  assert.equal(result.type, 'info');
  assert.match(result.text, /Строк: 2/);
  assert.equal(request.url, `/api/v1/jobs/${jobId}/result`);
  assert.equal(request.options.headers['X-Telegram-Init-Data'], 'signed-launch-data');
  assert.equal(request.options.cache, 'no-store');
});

test('expired or missing result explains TTL and restart without declaring job failed', async () => {
  environment(); const api = await load();
  globalThis.fetch = async () => new Response('', { status: 404 });
  await assert.rejects(api.getBackgroundResult(jobId, 'txt:docx'), /перезапуска/);
});

test('result reader rejects oversized actual bytes even without content-length', async () => {
  environment(); const api = await load(); let cancelled = false;
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(46 * 1024 * 1024)); },
    cancel() { cancelled = true; },
  }));
  await assert.rejects(api.getBackgroundResult(jobId, 'txt:docx'), /размер/);
  assert.equal(cancelled, true);
});

test('pre-aborted requests never start a status or result fetch', async () => {
  environment(); const api = await load(); let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw Error('unexpected'); };
  const controller = new AbortController(); controller.abort();
  await assert.rejects(api.getJobStatus(jobId, controller.signal), error => error.name === 'AbortError');
  await assert.rejects(api.getBackgroundResult(jobId, 'txt:docx', controller.signal), error => error.name === 'AbortError');
  assert.equal(calls, 0);
});

test('one shared budget bounds manual queue and result controls and expires monotonically', async () => {
  environment(); const api = await load();
  const originalPerformance = Object.getOwnPropertyDescriptor(globalThis, 'performance');
  let now = 0; let calls = 0;
  Object.defineProperty(globalThis, 'performance', { configurable: true, value: { now: () => now } });
  globalThis.fetch = async url => {
    calls += 1;
    if (url === '/api/v1/session') return Response.json({ ok: true, user_id: 11 });
    return Response.json({ capacity: 3, active: 0, waiting: 0, waiting_limit: 20, accepting: true });
  };
  try {
    for (let index = 0; index < 10; index += 1) await api.getQueueStatus();
    await assert.rejects(api.getBackgroundResult(jobId, 'txt:docx'), error => error.status === 429);
    assert.equal(calls, 10);
    assert.equal(await api.getVerifiedOwner(), 11, 'session verification uses the exempt session endpoint');
    now = 60000;
    assert.equal((await api.getQueueStatus()).capacity, 3);
    assert.equal(calls, 12);
  } finally { Object.defineProperty(globalThis, 'performance', originalPerformance); }
});

test('caller abort reaches an active status request and clears its request timer', async () => {
  environment(); const api = await load(); let signal;
  globalThis.fetch = async (_url, options) => {
    signal = options.signal;
    return await new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    });
  };
  const controller = new AbortController();
  const pending = api.getJobStatus(jobId, controller.signal);
  assert.equal(signal.aborted, false);
  controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(signal.aborted, true);
});

test('cancel reports the server state including a completion race and authenticates POST', async () => {
  environment(); const api = await load(); let request;
  globalThis.fetch = async (url, options) => { request = { url, options }; return Response.json(status('completed')); };
  const result = await api.cancelBackgroundJob(jobId);
  assert.equal(result.state, 'completed', 'a finished operation must not be relabelled cancelled');
  assert.equal(request.url, `/api/v1/jobs/${jobId}/cancel`);
  assert.equal(request.options.method, 'POST');
  assert.equal(request.options.headers['X-Telegram-Init-Data'], 'signed-launch-data');
  assert.equal(request.options.cache, 'no-store');
});

test('cancel network failure and foreign/mismatched responses never invent cancelled state', async () => {
  environment(); let api = await load();
  globalThis.fetch = async () => { throw new Error('offline'); };
  await assert.rejects(api.cancelBackgroundJob(jobId), /offline/);
  api = await load(); globalThis.fetch = async () => Response.json(status('cancelled'), { status: 404 });
  await assert.rejects(api.cancelBackgroundJob(jobId), error => error.status === 404);
  api = await load(); globalThis.fetch = async () => Response.json({ ...status('cancelled'), job_id: 'B'.repeat(32) });
  await assert.rejects(api.cancelBackgroundJob(jobId), /ответ/);
});

test('explicit create key is preserved for manual resubmission of the same request', async () => {
  environment(); const api = await load(); const headers = [];
  globalThis.XMLHttpRequest = class {
    upload = {}; status = 202;
    open() {} setRequestHeader(name, value) { if (name === 'Idempotency-Key') headers.push(value); }
    getResponseHeader(name) { return name === 'Content-Type' ? 'application/json' : null; }
    send() { this.response = new Blob([JSON.stringify(status('queued'))]); queueMicrotask(() => this.onload()); }
  };
  const file = new File(['hello'], 'input.txt'); const key = 'same-logical-request-12345';
  await api.createBackgroundJob(file, 'txt:docx', '', undefined, undefined, key);
  await api.createBackgroundJob(file, 'txt:docx', '', undefined, undefined, key);
  assert.deepEqual(headers, [key, key]);
});

test('retry sends original job ID, new file/parameters and required idempotency header', async () => {
  environment(); const api = await load(); let request;
  globalThis.XMLHttpRequest = class {
    upload = {}; status = 202;
    open(method, url) { request = { method, url, headers: {} }; }
    setRequestHeader(name, value) { request.headers[name] = value; }
    getResponseHeader(name) { return name === 'Content-Type' ? 'application/json' : null; }
    send(form) { request.form = form; this.response = new Blob([JSON.stringify({ ...status('queued'), job_id: 'B'.repeat(32) })]); queueMicrotask(() => this.onload()); }
  };
  const result = await api.retryBackgroundJob(jobId, new File(['%PDF-1'], 'new.pdf'), 'pdf:extract', '1,3-5', 'retry-logical-request-12345');
  assert.equal(result.job_id, 'B'.repeat(32));
  assert.equal(request.url, `/api/v1/jobs/${jobId}/retry`);
  assert.equal(request.headers['Idempotency-Key'], 'retry-logical-request-12345');
  assert.equal(request.headers['X-Telegram-Init-Data'], 'signed-launch-data');
  assert.equal(request.form.get('pages'), '1,3-5');
  assert.equal(request.form.get('action'), 'pdf:extract');
  assert.equal(await request.form.get('upload').text(), '%PDF-1');
});

test('unsafe retry IDs or keys and missing auth cannot start a control request', async () => {
  environment(); const api = await load(); let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw Error('unexpected'); };
  globalThis.XMLHttpRequest = class { constructor() { calls += 1; throw Error('unexpected'); } };
  const file = new File(['x'], 'input.txt');
  await assert.rejects(api.retryBackgroundJob('../secret', file, 'txt:docx', '', 'valid-key-request-12345'));
  await assert.rejects(api.retryBackgroundJob(jobId, file, 'txt:docx', '', 'bad\r\nheader'));
  window.Telegram.WebApp.initData = '';
  await assert.rejects(api.cancelBackgroundJob(jobId));
  await assert.rejects(api.retryBackgroundJob(jobId, file, 'txt:docx', '', 'valid-key-request-12345'));
  assert.equal(calls, 0);
});

test('profile uses signed Telegram identity, no-store and server-confirmed numbers', async () => {
  environment(); const api = await load(); const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return Response.json({
      plan: 'free', day_utc: '2026-11-14', daily_limit: 10, daily_used: 3,
      daily_remaining: 7, pack_remaining: 10, pro_expires_at: null,
      enforced: true, purchases_enabled: false,
    });
  };
  const profile = await api.getUsageSnapshot();
  assert.equal(profile.daily_remaining, 7);
  assert.equal(profile.pack_remaining, 10);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/v1/usage');
  assert.equal(requests[0].options.cache, 'no-store');
  assert.equal(requests[0].options.headers['X-Telegram-Init-Data'], 'signed-launch-data');
});

test('untrusted/invalid profile never becomes an account balance', async () => {
  environment(); const api = await load();
  globalThis.fetch = async () => Response.json({
    plan: 'pro', day_utc: '2026-11-14', daily_limit: 100, daily_used: 9,
    daily_remaining: 91, pack_remaining: 30, pro_expires_at: null,
    enforced: true, purchases_enabled: true,
  });
  await assert.rejects(api.getUsageSnapshot(), /некорректный профиль/);
});

test('profile access is denied without signed Telegram launch, no request is made', async () => {
  environment(); window.Telegram.WebApp.initData = ''; const api = await load();
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error('unexpected fetch'); };
  await assert.rejects(api.getUsageSnapshot(), error => error.status === 401);
  assert.equal(called, false);
});

test('profile correctly handles unauthorized and offline servers without fake balance', async () => {
  environment(); const api = await load();
  globalThis.fetch = async () => new Response(null, { status: 401 });
  await assert.rejects(api.getUsageSnapshot(), error => error.status === 401);
  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(api.getUsageSnapshot(), error => error.status === 503);
});

test('pre-aborted profile request never fetches data', async () => {
  environment(); const api = await load();
  let requests = 0;
  globalThis.fetch = async () => { requests += 1; return Response.json({}); };
  const signal = new AbortController(); signal.abort();
  await assert.rejects(api.getUsageSnapshot(signal.signal), error => error.name === 'AbortError');
  assert.equal(requests, 0);
});
