import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { nextBatchReorderFocus } from '../.test-dist/batchReorderFocus.js';

test('upward reorder retains focus on moved photo when another upward move is possible', () => {
  assert.deepEqual(nextBatchReorderFocus(3, -1, 5), { index: 2, direction: -1 });
});

test('downward reorder retains focus on moved photo for repeated keyboard moves', () => {
  assert.deepEqual(nextBatchReorderFocus(1, 1, 5), { index: 2, direction: 1 });
});

test('boundary moves focus the enabled opposite-direction button on the same photo', () => {
  assert.deepEqual(nextBatchReorderFocus(1, -1, 5), { index: 0, direction: 1 });
  assert.deepEqual(nextBatchReorderFocus(3, 1, 5), { index: 4, direction: -1 });
  assert.deepEqual(nextBatchReorderFocus(1, -1, 2), { index: 0, direction: 1 });
  assert.deepEqual(nextBatchReorderFocus(0, 1, 2), { index: 1, direction: -1 });
});

test('invalid or out-of-range requests cannot redirect keyboard focus', () => {
  for (const args of [
    [0, -1, 4], [3, 1, 4], [-1, 1, 4], [4, -1, 4],
    [0, 1, 1], [0, 1, 0], [1.5, -1, 4], [1, 1, NaN],
    [1, 0, 4], [1, 2, 4],
  ]) {
    assert.equal(nextBatchReorderFocus(...args), null, JSON.stringify(args));
  }
});

test('Mini App wires focus restoration to changed batch state and identifies photos', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(source, /import \{ nextBatchReorderFocus, type BatchReorderFocus, type BatchReorderDirection \} from '\.\/batchReorderFocus';/);
  assert.match(source, /const pendingBatchFocusRef = useRef<BatchReorderFocus \| null>\(null\);/);
  assert.match(source, /pendingBatchFocusRef\.current = target;/);
  assert.match(source, /const target = pendingBatchFocusRef\.current;[\s\S]*?pendingBatchFocusRef\.current = null;[\s\S]*?\.focus\(\);[\s\S]*?\}, \[batchFiles\]\);/);
  assert.match(source, /data-batch-position=\{index\}/);
  assert.match(source, /data-batch-direction="-1"/);
  assert.match(source, /data-batch-direction="1"/);
  assert.match(source, /aria-label=\{`Переместить фото \$\{index \+ 1\} \(\$\{photo\.name\}\) выше`\}/);
  assert.match(source, /aria-label=\{`Переместить фото \$\{index \+ 1\} \(\$\{photo\.name\}\) ниже`\}/);
  assert.doesNotMatch(source, /aria-label="Переместить (?:выше|ниже)"/);
});
