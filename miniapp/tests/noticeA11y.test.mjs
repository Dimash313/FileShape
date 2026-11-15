import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('notice state stores message and severity as one atomic value', () => {
  assert.match(app, /useState<\{ text: string; kind: 'status' \| 'alert' \} \| null>\(null\)/);
  assert.match(app, /const showNotice = \(text: string, kind: 'status' \| 'alert' = 'status'\) => setNotice\(\{ text, kind \}\)/);
  assert.match(app, /className="notice" role=\{notice\.kind\}>\{notice\.text\}/);
  assert.doesNotMatch(app, /className="notice" role="status"/);
});

test('invalid single and batch selections are assertive alerts', () => {
  for (const name of ['batchImageSelectionError(files)', 'singleFileSelectionError(next)']) {
    const start = app.indexOf(name);
    assert.ok(start >= 0, 'Missing validation: ' + name);
    const body = app.slice(start, start + 140);
    assert.match(body, /if \(error\) \{\s*showNotice\(error, 'alert'\);\s*return;/);
  }
});

test('PDF input limits and server validation errors announce as alerts', () => {
  for (const fragment of [
    'За одну операцию можно выбрать не более 150 страниц.',
    'Нельзя удалить все страницы PDF.',
    'Выбор слишком сложный.',
    'Максимум 150 страниц;',
    'Слишком много выбранных страниц.',
  ]) {
    const line = app.split('\n').find(x => x.includes(fragment) && x.includes('showNotice('));
    assert.ok(line, 'Missing alert notice: ' + fragment);
    assert.match(line, /, 'alert'\);/);
  }
  assert.match(app, /showNotice\(pageSelectionError \|\| 'Проверь выбранные страницы\.', 'alert'\)/);
});

test('caught request failures are alerts but confirmed results use polite status', () => {
  for (const message of [
    'Не удалось проверить статус.',
    'Не удалось обработать файл.',
    'Не удалось прочитать PDF.',
    'Номер задания не подтверждён.',
    'Не удалось объединить изображения.',
  ]) {
    const line = app.split('\n').find(x => x.includes(message) && x.includes('showNotice('));
    assert.ok(line, 'Missing caught error: ' + message);
    assert.match(line, /, 'alert'\);/);
  }
  for (const message of [
    'Готово! Файл сохранён на устройство.',
    'Информация о PDF получена.',
    'Задание принято.',
    'Готово! PDF создан из ',
  ]) {
    const line = app.split('\n').find(x => x.includes(message) && x.includes('showNotice('));
    assert.ok(line, 'Missing confirmation: ' + message);
    assert.doesNotMatch(line, /, 'alert'\);/);
  }
  assert.match(app, /status\.state === 'failed' \? 'alert' : 'status'/);
});

test('closing notices and navigating sections clear the current notice', () => {
  assert.match(app, /<button aria-label="Закрыть" onClick=\{\(\) => setNotice\(null\)\}/);
  assert.match(app, /onClick=\{\(\) => \{ tapFeedback\(\); setTab\(item\.tab\); setNotice\(null\); \}\}/);
  assert.doesNotMatch(app, /setNotice\(''\)/);
});

test('PDF page input exposes semantic validation error and links its message', () => {
  const field = app.match(/<input type="text" value=\{pages\}[\s\S]*?\/>/)?.[0];
  assert.ok(field, 'PDF pages input missing');
  assert.match(field, /aria-invalid=\{Boolean\(pageSelectionError\)\}/);
  assert.match(field, /aria-describedby=\{pageSelectionError \? 'pdf-page-selection-error' : undefined\}/);
  assert.doesNotMatch(field, /aria-invalid=\{!validPageSelection\}/);
  assert.match(app, /\{selectedOption\?\.pages && pageSelectionError && <div id="pdf-page-selection-error" className="pdf-inline-error" role="alert">/);

  // Range syntax may be valid even though the request itself is invalid.
  assert.match(app, /selectedPageNumbers\.size > 150 \? 'За одну операцию можно выбрать максимум 150 страниц\.'/);
  assert.match(app, /selectedAction === 'pdf:remove' && pdfPageCount !== null && selectedPageNumbers\.size === pdfPageCount/);
});
