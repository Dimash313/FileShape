import test from 'node:test';
import assert from 'node:assert/strict';
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
