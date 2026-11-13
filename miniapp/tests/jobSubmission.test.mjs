import test from 'node:test';
import assert from 'node:assert/strict';
import { createIdempotencyKey, SubmissionKeeper, retryPagesAreValid } from '../.test-dist/jobSubmission.js';

const id = 'A'.repeat(32);
const file = () => new File(['valid input'], 'private.txt', { type: 'text/plain', lastModified: 123 });
function keeper() {
  let calls = 0;
  return { intents: new SubmissionKeeper(() => `secure-test-key-${++calls}`), calls: () => calls };
}

test('idempotency keys use the cryptographic UUID source when available', () => {
  const uuid = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0';
  assert.equal(createIdempotencyKey({ randomUUID: () => uuid }), uuid);
  assert.match(createIdempotencyKey(), /^[0-9a-f-]{32,36}$/i);
});

test('cryptographic byte fallback supplies a bounded hexadecimal key', () => {
  let calls = 0;
  const source = { getRandomValues(bytes) { calls += 1; assert.equal(bytes.byteLength, 16); bytes.set(Array.from({ length: 16 }, (_, index) => index)); } };
  assert.equal(createIdempotencyKey(source), '000102030405060708090a0b0c0d0e0f');
  assert.equal(calls, 1);
  assert.equal(createIdempotencyKey({ randomUUID() { throw Error('unsupported'); }, ...source }), '000102030405060708090a0b0c0d0e0f');
});

test('missing cryptography fails instead of using weak keys', () => {
  assert.throws(() => createIdempotencyKey({}), /безопасную/);
  assert.throws(() => createIdempotencyKey({ randomUUID: () => 'invalid' }), /безопасную/);
});

test('manual resubmission after an unknown response reuses the exact intent and key', () => {
  const { intents, calls } = keeper(); const input = file();
  const first = intents.prepare(input, 'txt:docx', '');
  const again = intents.prepare(input, 'txt:docx', '');
  assert.equal(again, first);
  assert.equal(again.key, first.key);
  assert.equal(calls(), 1);
  assert.equal(intents.current.file, input);
});

test('changed file, action, pages or retry parent creates a new logical intent', () => {
  const { intents, calls } = keeper(); const input = file();
  let previous = intents.prepare(input, 'txt:docx', '');
  for (const args of [
    [file(), 'txt:docx', ''],
    [input, 'txt:info', ''],
    [input, 'txt:info', '1'],
    [input, 'txt:info', '1', id],
  ]) {
    const next = intents.prepare(...args);
    assert.notEqual(next, previous);
    assert.notEqual(next.key, previous.key);
    previous = next;
  }
  assert.equal(calls(), 5);
  assert.equal(intents.current, previous);
});

test('confirmed acceptance keeps the source for that ID and creates a fresh key for retry', () => {
  const { intents } = keeper(); const input = file();
  const original = intents.prepare(input, 'txt:docx', '');
  intents.accept(original, id);
  assert.equal(intents.retrySource(id), original);
  assert.equal(intents.retrySource('B'.repeat(32)), null);
  const retry = intents.prepare(input, original.action, original.pages, id);
  assert.notEqual(retry.key, original.key);
  assert.equal(retry.retryOf, id);
  assert.equal(intents.prepare(input, original.action, original.pages, id), retry, 'an ambiguous retry reuses its key');
  intents.accept(retry, 'B'.repeat(32));
  assert.equal(intents.retrySource(id), null);
  assert.equal(intents.retrySource('B'.repeat(32)), retry);
});

test('a fresh operation after confirmed acceptance never reuses the accepted key', () => {
  const { intents } = keeper(); const input = file();
  const first = intents.prepare(input, 'txt:docx', ''); intents.accept(first, id);
  const next = intents.prepare(input, 'txt:docx', '');
  assert.notEqual(next.key, first.key);
  assert.equal(next.acceptedJobId, undefined);
});

test('a late acceptance cannot attach an ID to a replacement or overwrite confirmed acceptance', () => {
  const { intents } = keeper();
  const old = intents.prepare(file(), 'txt:docx', '');
  const current = intents.prepare(file(), 'txt:docx', '');
  intents.accept(old, id);
  assert.equal(current.acceptedJobId, undefined);
  intents.accept(current, 'B'.repeat(32));
  intents.accept(current, id);
  assert.equal(current.acceptedJobId, 'B'.repeat(32));
});

test('clearing releases the only held file and source descriptor', () => {
  const { intents } = keeper(); const pending = intents.prepare(file(), 'txt:docx', '');
  intents.accept(pending, id); intents.clear();
  assert.equal(intents.current, null);
  assert.equal(intents.retrySource(id), null);
  intents.accept(pending, 'B'.repeat(32));
  assert.equal(intents.current, null);
});

test('empty or oversized inputs cannot replace a valid bounded source', () => {
  const { intents } = keeper(); const pending = intents.prepare(file(), 'txt:docx', '');
  assert.throws(() => intents.prepare(new File([], 'empty.txt'), 'txt:docx', ''), /непустой/);
  assert.throws(() => intents.prepare(new File([new Uint8Array(20 * 1024 * 1024 + 1)], 'large.txt'), 'txt:docx', ''), /20/);
  assert.equal(intents.current, pending);
});


test('retry ranges are required only for PDF extract/remove actions', () => {
  for (const action of ['txt:docx', 'txt:info', 'audio:mp3', 'pdf:rotate', 'docx:txt']) {
    assert.equal(retryPagesAreValid(action, ''), true);
  }
  assert.equal(retryPagesAreValid('txt:info', 'not a PDF range'), true);
});

test('PDF retries reject empty, malformed, reversed, excessive and out-of-bounds ranges', () => {
  const invalid = ['', ' ', ',', '1,', ',1', '1,,2', 'a', '0', '-1', '2-1', '1-251', '251', '1-151', '0-1', '1-2-3', '1.5', '+1', '9'.repeat(90), ' '.repeat(91) + '1'];
  for (const action of ['pdf:extract', 'pdf:remove']) {
    for (const pages of invalid) assert.equal(retryPagesAreValid(action, pages), false, `${action}: ${JSON.stringify(pages)}`);
  }
});

test('PDF retries accept bounded ascending ranges and normal whitespace', () => {
  for (const pages of ['1', '250', '1-150', '101-250', '1,3-5', ' 1, 3 - 5 ']) {
    assert.equal(retryPagesAreValid('pdf:extract', pages), true, pages);
    assert.equal(retryPagesAreValid('pdf:remove', pages), true, pages);
  }
});

test('retry page count uses unique pages so overlapping ranges remain valid', () => {
  assert.equal(retryPagesAreValid('pdf:extract', '1-150,1-150'), true);
  assert.equal(retryPagesAreValid('pdf:remove', '1-100,50-150'), true);
  assert.equal(retryPagesAreValid('pdf:extract', '1-150,150'), true);
  assert.equal(retryPagesAreValid('pdf:extract', '1-100,100-151'), false);
  assert.equal(retryPagesAreValid('pdf:remove', '1-150,151'), false);
});
