import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describeTransfer } from '../.test-dist/transferPresentation.js';

test('measured browser upload reports exact values including 0 and 100 percent', () => {
  for (const percent of [0, 1, 42, 99, 100]) {
    const view = describeTransfer({ stage: 'upload', percent });
    assert.equal(view.uploadPercent, percent);
    assert.equal(view.uploadValueText, `Передано ${percent}% файла`);
    assert.equal(view.label, 'Загрузка файла');
  }
});

test('indeterminate and malformed upload measurements never invent a percentage', () => {
  for (const percent of [null, -1, 101, NaN, Infinity, 1.5]) {
    const view = describeTransfer({ stage: 'upload', percent });
    assert.equal(view.uploadPercent, null);
    assert.equal(view.uploadValueText, null);
    assert.match(view.detail, /Передаём файл/);
  }
});

test('background validation is an indeterminate server admission wait, not accepted job', () => {
  const view = describeTransfer({ stage: 'validation', percent: 90 });
  assert.equal(view.uploadPercent, null);
  assert.equal(view.uploadValueText, null);
  assert.match(view.label, /Ожидание подтверждения сервера/);
  assert.match(view.detail, /Ожидаем подтверждения приёма задания/);
});

test('legacy processing waits for response without implying server progress', () => {
  const view = describeTransfer({ stage: 'processing', percent: 80 });
  assert.equal(view.uploadPercent, null);
  assert.equal(view.uploadValueText, null);
  assert.match(view.label, /Ожидание результата сервера/);
  assert.match(view.detail, /Ожидаем ответа по операции/);
});

test('ProgressIndicator uses the shared presentation and labels measurable progress for AT', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(source, /import \{ describeTransfer \} from '\.\/transferPresentation';/);
  assert.match(source, /const view = describeTransfer\(progress\)/);
  assert.match(source, /role="progressbar" aria-label="Загрузка файла на сервер"/);
  assert.match(source, /aria-valuenow=\{view\.uploadPercent\}/);
  assert.match(source, /aria-valuetext=\{view\.uploadValueText \?\? undefined\}/);
  assert.doesNotMatch(source.slice(source.indexOf('function ProgressIndicator('), source.indexOf('export default function App()')), /Ожидание или обработка/);
});
