import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { activeTools, acceptForTool } from '../.test-dist/toolCatalog.js';

test('Mini App catalog exposes only implemented tools', () => {
  const keys = activeTools.map(tool => tool.key);
  assert.deepEqual(keys, ['pdf', 'image', 'audio', 'documents', 'archive', 'batch']);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(!activeTools.some(tool => /сканер|scanner/i.test(tool.title)));
});

test('each single-file tool opens a category-specific native picker', () => {
  const expected = {
    pdf: ['.pdf'],
    image: ['.jpg', '.jpeg', '.png', '.webp'],
    audio: ['.mp3', '.ogg', '.oga', '.wav', '.m4a', '.flac'],
    documents: ['.docx', '.txt'],
    archive: ['.zip'],
  };
  for (const [key, extensions] of Object.entries(expected)) {
    const options = acceptForTool(key).split(',');
    for (const extension of extensions) {
      assert.ok(options.includes(extension), key + ' missing ' + extension);
    }
    assert.notEqual(acceptForTool(key), '', key + ' must not use unrestricted picker');
  }
});

test('generic upload resets filters; batch uses its separate picker', () => {
  assert.equal(acceptForTool(), '');
  assert.equal(acceptForTool('batch'), '');
  assert.equal(activeTools.find(tool => tool.key === 'batch').accept, null);
});

test('opening or cancelling single-file picker preserves the prepared batch', () => {
  // Source-level regression: this component uses native input.click(), which
  // cannot be cancelled reliably inside a headless Node test environment.
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const pickStart = source.indexOf('  const pick = (tool?: SingleFileToolKey) => {');
  const pickEnd = source.indexOf('  const pickBatch =', pickStart);
  assert.ok(pickStart >= 0 && pickEnd > pickStart, 'Single-file picker handler not found');
  const picker = source.slice(pickStart, pickEnd);
  assert.doesNotMatch(picker, /setBatchMode\(false\)/,
    'Picker open/cancel must not hide the selected photo batch');

  const acceptStart = source.indexOf('  const acceptFile = (next?: File) => {');
  const acceptEnd = source.indexOf('  const clear =', acceptStart);
  assert.ok(acceptStart >= 0 && acceptEnd > acceptStart, 'File acceptance handler not found');
  const acceptance = source.slice(acceptStart, acceptEnd);
  assert.ok(acceptance.includes('setBatchMode(false)'),
    'After a valid single-file selection, switch out of batch mode');
  assert.ok(acceptance.indexOf('setBatchMode(false)') > acceptance.indexOf('setFile(next)'),
    'Switch mode only after a selected file has been accepted');
});
