import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_MINIAPP_FILE_BYTES, singleFileSelectionError, batchImageSelectionError } from '../.test-dist/filePreflight.js';

const image = (name, size) => ({ name, size });

test('single-file preflight rejects empty and malformed lengths', () => {
  for (const size of [0, -1, NaN, Infinity, -Infinity, 1.5]) {
    assert.match(singleFileSelectionError({ size }), /пуст|размер не определён/i);
  }
});

test('single-file preflight preserves existing 20 MiB boundary', () => {
  assert.equal(singleFileSelectionError({ size: 1 }), null);
  assert.equal(singleFileSelectionError({ size: MAX_MINIAPP_FILE_BYTES }), null);
  assert.match(singleFileSelectionError({ size: MAX_MINIAPP_FILE_BYTES + 1 }), /20 МБ/);
});

test('batch preflight enforces 2–8 files without discarding valid formats', () => {
  assert.match(batchImageSelectionError([]), /от 2 до 8/);
  assert.match(batchImageSelectionError([image('a.jpg', 5)]), /от 2 до 8/);
  assert.equal(batchImageSelectionError(Array.from({ length: 8 }, (_, i) => image('a' + i + '.png', 1))), null);
  assert.match(batchImageSelectionError(Array.from({ length: 9 }, (_, i) => image('a' + i + '.png', 1))), /от 2 до 8/);
});

test('batch preflight reports empty files separately from unsupported formats', () => {
  assert.match(batchImageSelectionError([image('a.jpg', 0), image('b.png', 1)]), /пуст/i);
  assert.match(batchImageSelectionError([image('a.jpg', NaN), image('b.png', 1)]), /размер не определён/i);
  assert.match(batchImageSelectionError([image('a.jpg', 1), image('b.gif', 1)]), /только JPG/);
  assert.equal(batchImageSelectionError([image('a.JPG', 1), image('b.WeBp', 1)]), null);
});

test('batch preflight enforces total upload limit at the exact boundary', () => {
  assert.equal(batchImageSelectionError([
    image('a.jpeg', MAX_MINIAPP_FILE_BYTES - 1), image('b.png', 1),
  ]), null);
  assert.match(batchImageSelectionError([
    image('a.jpeg', MAX_MINIAPP_FILE_BYTES), image('b.png', 1),
  ]), /20 МБ/);
});
