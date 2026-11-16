import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const marker = '/* Interfaces UX: 44px touch targets for small-screen Telegram WebViews (#139). */';
const index = css.lastIndexOf(marker);
assert.ok(index >= 0, 'Touch target override block must exist');
const overrides = css.slice(index);

function declarationBlock(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = overrides.match(new RegExp(escaped + '\\s*\\{([^}]*)\\}'));
  assert.ok(match, 'Missing CSS override for ' + selector);
  return match[1];
}

function has44(rule, property) {
  assert.match(rule, new RegExp('(?:^|[;\\s])' + property + ':\\s*44px\\s*;'), property + ' must be 44px');
}

test('profile and notice close icon buttons have 44px clickable boxes', () => {
  for (const selector of ['.icon-button', '.notice button']) {
    const rule = declarationBlock(selector);
    has44(rule, 'width');
    has44(rule, 'height');
  }
  assert.match(declarationBlock('.notice button'), /flex:\s*0 0 44px\s*;/);
});

test('compact text actions remain 44px minimum in both dimensions', () => {
  const rule = declarationBlock('.text-button');
  has44(rule, 'min-width');
  has44(rule, 'min-height');
});

test('pagination, page presets, job checks and usage refresh get 44px height', () => {
  assert.match(overrides,
    /\.page-presets-row button,\s*\.pdf-bulk-actions button,\s*\.pdf-grid-navigation button,\s*\.job-check,\s*\.usage-heading button\s*\{\s*min-height:\s*44px\s*;/);
});

test('batch reorder controls remain usable on narrow screens', () => {
  const rule = declarationBlock('.batch-row button');
  has44(rule, 'min-width');
  has44(rule, 'min-height');
  assert.ok(!/(?:^|[;\s])width:\s*\d+px\s*;/.test(rule), 'Do not set a fixed width for batch controls');
});

test('notifications wrap and existing focus, reduced-motion and narrow-screen rules remain', () => {
  assert.match(declarationBlock('.notice'), /overflow-wrap:\s*anywhere\s*;/);
  assert.match(css, /button:focus-visible/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /@media\s*\(forced-colors:\s*active\)/);
  assert.match(css, /@media\s*\(max-width:\s*370px\)/);
});
