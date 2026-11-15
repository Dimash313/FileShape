import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

function token(name) {
  const match = css.match(new RegExp(name + ':\\s*(#[0-9a-f]{6})\\s*;', 'i'));
  assert.ok(match, 'Missing CSS token ' + name);
  return match[1];
}

function luminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi);
  assert.ok(channels && channels.length === 3, 'Expected six-digit hex color');
  const [r, g, b] = channels.map(channel => {
    const value = parseInt(channel, 16) / 255;
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  });
  return .2126 * r + .7152 * g + .0722 * b;
}

function contrast(first, second) {
  const a = luminance(first), b = luminance(second);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

test('every color in the Mini App stylesheet is achromatic', () => {
  // CSS issue references and documentation comments are not rendered colors.
  const declarations = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const colors = [...declarations.matchAll(/#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})\b/gi)];
  assert.ok(colors.length >= 100, 'Unexpectedly few CSS colors inspected');
  for (const [, raw] of colors) {
    const hex = raw.toLowerCase();
    if (hex.length === 3 || hex.length === 4) {
      assert.equal(hex[0], hex[1], '#' + hex);
      assert.equal(hex[1], hex[2], '#' + hex);
    } else {
      assert.equal(hex.slice(0, 2), hex.slice(2, 4), '#' + hex);
      assert.equal(hex.slice(2, 4), hex.slice(4, 6), '#' + hex);
    }
  }
  assert.doesNotMatch(declarations, /\b(?:rgba?|hsla?)\s*\(/i, 'Color functions must be reviewed for non-neutral channels');
});

test('main text and button states retain readable contrast', () => {
  assert.ok(contrast(token('--text-primary'), token('--canvas')) >= 7);
  assert.ok(contrast(token('--text-secondary'), token('--surface')) >= 4.5);
  assert.ok(contrast(token('--text-muted'), token('--canvas')) >= 4.5);
  assert.ok(contrast(token('--accent'), token('--accent-ink')) >= 7);
});

test('complete workflows and mobile accessibility remain covered', () => {
  for (const selector of [
    '.upload-area', '.selected-file', '.tool-card', '.server-option.active',
    '.pdf-page-number.selected', '.batch-row', '.history-item',
    '.background-jobs', '.queue-panel', '.profile-card', '.nav-item.active',
  ]) {
    assert.ok(css.includes(selector), 'Missing style for ' + selector);
  }
  assert.match(css, /button:focus-visible/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /@media\s*\(forced-colors:\s*active\)/);
  assert.match(css, /safe-area-inset-bottom/);
  assert.match(app, /aria-current=\{tab === item\.tab \? 'page' : undefined\}/);
  assert.match(app, /aria-pressed=\{format === item\.value\}/);
  // Progress rendering delegates validation to a typed presenter; its cases are
  // exercised by transferPresentation.test.mjs, not brittle JSX source patterns.
  assert.match(app, /const view = describeTransfer\(progress\)/);
  assert.match(app, /view\.uploadPercent !== null/);
  assert.match(app, /aria-valuenow=\{view\.uploadPercent\}/);
  assert.match(html, /name="theme-color" content="#080808"/);
  assert.doesNotMatch(app, /className="blue-dot"/);
});
