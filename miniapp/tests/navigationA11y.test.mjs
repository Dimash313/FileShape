import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');

test('keyboard skip link precedes other interactive controls and targets focusable main', () => {
  const skip = app.indexOf('<a className="skip-link" href="#main-content">Перейти к содержимому</a>');
  const picker = app.indexOf('ref={inputRef} className="visually-hidden"');
  const main = app.indexOf('<main id="main-content" tabIndex={-1}>');
  assert.ok(skip !== -1 && picker > skip && main > picker);
});

test('native hidden pickers do not steal keyboard focus or appear to screen readers', () => {
  // JSX arrow callbacks contain '>' inside attribute expressions. Do not
  // terminate the input match at the first '>' character.
  const singleStart = app.indexOf('<input ref={inputRef}');
  const batchStart = app.indexOf('<input ref={batchInputRef}');
  const headerStart = app.indexOf('<header className="topbar">');
  assert.ok(singleStart >= 0 && batchStart > singleStart && headerStart > batchStart);
  const single = app.slice(singleStart, batchStart);
  const batch = app.slice(batchStart, headerStart);
  for (const input of [single, batch]) {
    assert.match(input, /tabIndex=\{-1\}/);
    assert.match(input, /aria-hidden="true"/);
    assert.match(input, /type="file"/);
  }
  assert.match(app, /inputRef\.current\.click\(\)/);
  assert.match(app, /batchInputRef\.current\.click\(\)/);
});

test('tab changes focus the screen title only after the first section changes', () => {
  assert.match(app, /const \[tab, setTab\] = useState<Tab>\('home'\);/);
  assert.match(app, /const previousTabRef = useRef<Tab>\('home'\);/);
  assert.match(app, /const screenTitleRef = useRef<HTMLHeadingElement>\(null\);/);
  assert.match(app, /if \(previousTabRef\.current === tab\) return;/);
  assert.match(app, /previousTabRef\.current = tab;\s*screenTitleRef\.current\?\.focus\(\);/);
  assert.match(app, /\}, \[tab\]\);/);
  assert.match(app, /<h1 ref=\{screenTitleRef\} id="screen-title" tabIndex=\{-1\}>/);
});

test('skip link is hidden until focused and remains visible above sticky header', () => {
  const marker = '/* Interfaces UX: in-app section keyboard navigation and skip link (#172). */';
  const section = css.slice(css.lastIndexOf(marker));
  assert.ok(section.startsWith(marker), 'Missing focused-accessibility override');
  assert.match(section, /\.skip-link\s*\{[^}]*position:\s*fixed;[^}]*transform:\s*translateY\(-200%\);[^}]*pointer-events:\s*none;/s);
  assert.match(section, /\.skip-link:focus\s*\{[^}]*transform:\s*none;[^}]*opacity:\s*1;[^}]*pointer-events:\s*auto;[^}]*outline:/s);
  assert.match(section, /env\(safe-area-inset-top\)/);
  assert.match(section, /#main-content,\s*#screen-title\s*\{\s*scroll-margin-top:/);
});

test('navigation remains semantic with a single active section and no stale Scanner', () => {
  assert.match(app, /<nav className="bottom-nav" aria-label="Основная навигация">/);
  assert.match(app, /aria-current=\{tab === item\.tab \? 'page' : undefined\}/);
  assert.doesNotMatch(app, /Сканер появится позже|ScanLine/);
});

test('skip link aligns with the centered shell and supports system forced colors', () => {
  assert.match(css, /\.app-shell\{max-width:600px;/,
    'Desktop shell width is used by the aligned skip link');
  const marker = '/* Interfaces UX: in-app section keyboard navigation and skip link (#172). */';
  const section = css.slice(css.lastIndexOf(marker));
  assert.match(section, /left:\s*max\(16px,\s*calc\(\(100vw - 600px\) \/ 2 \+ 16px\)\);/);
  assert.match(section, /max-width:\s*calc\(100vw - 32px\);/);
  assert.match(section, /box-sizing:\s*border-box;/);
  assert.match(section, /@media \(forced-colors: active\)\s*\{\s*\.skip-link:focus\s*\{[^}]*background:\s*Canvas;[^}]*color:\s*CanvasText;[^}]*border-color:\s*Highlight;[^}]*outline-color:\s*Highlight;/s);
});
