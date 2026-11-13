import test from 'node:test';
import assert from 'node:assert/strict';
import { loadJobRefs, saveJobRefs, clearJobRefs } from '../.test-dist/jobRefs.js';

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}
const now = 10000;
const key = owner => `fileshape:jobs:v43:${owner}`;
const ref = (number = 1, time = now - 10) => ({
  jobId: String(number).padStart(32, 'A'), action: 'txt:docx',
  createdAt: time, updatedAt: time,
});

test('references are owner-scoped and clearing one owner preserves another', () => {
  const storage = new MemoryStorage();
  assert.equal(saveJobRefs(storage, 11, [ref(1)], now), true);
  assert.equal(saveJobRefs(storage, 12, [ref(2)], now), true);
  assert.deepEqual(loadJobRefs(storage, 11, now), [ref(1)]);
  assert.deepEqual(loadJobRefs(storage, 12, now), [ref(2)]);
  assert.equal(clearJobRefs(storage, 11), true);
  assert.deepEqual(loadJobRefs(storage, 11, now), []);
  assert.deepEqual(loadJobRefs(storage, 12, now), [ref(2)]);
});

test('writes retain only opaque reference fields and never private extras', () => {
  const storage = new MemoryStorage();
  const input = { ...ref(), name: 'private.pdf', blob: 'file-bytes', initData: 'signed-secret', state: 'completed' };
  assert.equal(saveJobRefs(storage, 11, [input], now), true);
  assert.deepEqual(JSON.parse(storage.getItem(key(11))), [ref()]);
  assert.deepEqual(input.name, 'private.pdf', 'caller data was not mutated');
});

test('load sanitizes existing entries and rewrites persisted data', () => {
  const storage = new MemoryStorage();
  storage.setItem(key(11), JSON.stringify([{ ...ref(), filename: 'private.txt', launchData: 'secret' }]));
  assert.deepEqual(loadJobRefs(storage, 11, now), [ref()]);
  assert.deepEqual(JSON.parse(storage.getItem(key(11))), [ref()]);
});

test('expiry is one hour from acceptance even if updated recently', () => {
  const storage = new MemoryStorage();
  const expired = { ...ref(1, now - 3600), updatedAt: now };
  storage.setItem(key(11), JSON.stringify([expired, ref(2, now - 3599)]));
  assert.deepEqual(loadJobRefs(storage, 11, now), [ref(2, now - 3599)]);
  assert.deepEqual(loadJobRefs(storage, 11, now + 1), []);
  assert.equal(storage.getItem(key(11)), null);
});

test('malformed, oversized and non-array stored payloads are removed safely', () => {
  const storage = new MemoryStorage();
  for (const raw of ['{', '{}', 'null', 'x'.repeat(16385), JSON.stringify('а'.repeat(9000))]) {
    storage.setItem(key(11), raw);
    assert.deepEqual(loadJobRefs(storage, 11, now), []);
    assert.equal(storage.getItem(key(11)), null);
  }
});

test('invalid references, future timestamps and unknown actions are dropped', () => {
  const storage = new MemoryStorage();
  const invalid = [null, 1, {}, { ...ref(), jobId: '../private' },
    { ...ref(), action: 'execute:anything' }, { ...ref(), createdAt: 0 },
    { ...ref(), createdAt: now + 31, updatedAt: now + 31 },
    { ...ref(), updatedAt: now + 31 }, { ...ref(), updatedAt: now - 20 },
    { ...ref(), updatedAt: Infinity }, { ...ref(), createdAt: NaN }];
  assert.equal(saveJobRefs(storage, 11, [...invalid, ref(2)], now), true);
  assert.deepEqual(loadJobRefs(storage, 11, now), [ref(2)]);
});

test('references are unique, latest first and bounded to twelve', () => {
  const storage = new MemoryStorage();
  const refs = Array.from({ length: 20 }, (_, index) => ref(index + 1, now - 50 + index));
  saveJobRefs(storage, 11, [...refs, refs[19]], now);
  const actual = loadJobRefs(storage, 11, now);
  assert.equal(actual.length, 12);
  assert.equal(new Set(actual.map(item => item.jobId)).size, 12);
  assert.deepEqual(actual, refs.slice(8).reverse());
});

test('invalid owners and clock values never access other storage', () => {
  const storage = { getItem() { throw new Error('unexpected access'); }, setItem() { throw new Error('unexpected access'); }, removeItem() { throw new Error('unexpected access'); } };
  for (const owner of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.deepEqual(loadJobRefs(storage, owner, now), []);
    assert.equal(saveJobRefs(storage, owner, [ref()], now), false);
    assert.equal(clearJobRefs(storage, owner), false);
  }
  assert.deepEqual(loadJobRefs(storage, 11, NaN), []);
  assert.equal(saveJobRefs(storage, 11, [ref()], 0), false);
});

test('storage denial is contained and never breaks current-session processing', () => {
  const storage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } };
  assert.deepEqual(loadJobRefs(storage, 11, now), []);
  assert.equal(saveJobRefs(storage, 11, [ref()], now), false);
  assert.equal(clearJobRefs(storage, 11), false);
});

test('a successful read can still return sanitized refs when writes are denied', () => {
  const storage = { getItem() { return JSON.stringify([ref()]); }, setItem() { throw new Error('quota'); }, removeItem() { throw new Error('quota'); } };
  assert.deepEqual(loadJobRefs(storage, 11, now), [ref()]);
});
