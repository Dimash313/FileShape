import { telegramInitData } from './telegram';

export type ServerAction = { code: string; label: string; pages?: boolean };
export type ServerResult = { type: 'info'; text: string } | { type: 'file'; blob: Blob; name: string };

export const actionsFor: Record<string, ServerAction[]> = {
  image: [
    { code: 'img:PDF', label: '→ PDF' },
    { code: 'img:compress', label: 'Оптимизировать WebP' },
  ],
  pdf: [
    { code: 'pdf:info', label: 'Количество страниц' },
    { code: 'pdf:first', label: 'Извлечь первую' },
    { code: 'pdf:rotate', label: 'Повернуть на 90°' },
    { code: 'pdf:extract', label: 'Извлечь страницы', pages: true },
    { code: 'pdf:remove', label: 'Удалить страницы', pages: true },
  ],
  audio: [
    { code: 'audio:info', label: 'Информация об аудио' },
    { code: 'audio:mp3', label: '→ MP3' },
    { code: 'audio:ogg', label: '→ OGG' },
    { code: 'audio:wav', label: '→ WAV' },
  ],
  docx: [{ code: 'docx:info', label: 'Информация' }, { code: 'docx:txt', label: '→ TXT' }],
  txt: [{ code: 'txt:info', label: 'Информация' }, { code: 'txt:docx', label: '→ DOCX' }],
  zip: [{ code: 'zip:list', label: 'Просмотреть содержимое' }],
};

const outputExtension: Record<string, string> = {
  'img:PDF': 'pdf', 'img:compress': 'webp',
  'pdf:first': 'pdf', 'pdf:rotate': 'pdf',
  'pdf:extract': 'pdf', 'pdf:remove': 'pdf',
  'audio:mp3': 'mp3', 'audio:ogg': 'ogg', 'audio:wav': 'wav',
  'docx:txt': 'txt', 'txt:docx': 'docx',
};

function friendlyInfo(action: string, info: Record<string, unknown>): string {
  if (action === 'pdf:info') return `📄 Страниц: ${info.pages ?? '—'}`;
  if (action === 'audio:info') return `🎧 Длительность: ${info.seconds ?? '—'} сек. · Кодек: ${info.codec ?? '—'}`;
  if (action === 'txt:info') return `📝 Строк: ${info.lines ?? '—'}, символов: ${info.characters ?? '—'}`;
  if (action === 'docx:info') return `📝 Абзацев: ${info.paragraphs ?? '—'}, таблиц: ${info.tables ?? '—'}`;
  if (action === 'zip:list') {
    const names = Array.isArray(info.names) ? info.names.slice(0, 15).map(name => String(name)) : [];
    return `📦 Файлов: ${info.files ?? 0}\n${names.join('\n') || 'Архив пуст.'}`;
  }
  return 'Информация получена.';
}

export async function runServerAction(file: File, action: string, pages: string): Promise<ServerResult> {
  const raw = telegramInitData();
  if (!raw) throw new Error('Для серверных инструментов открой FileShape через Telegram.');
  const data = new FormData();
  data.append('upload', file, file.name);
  data.append('action', action);
  if (pages) data.append('pages', pages);
  // Relative URL: frontend and API must be served under one HTTPS origin.
  const response = await fetch('/api/v1/convert', {
    method: 'POST',
    headers: { 'X-Telegram-Init-Data': raw },
    body: data,
    cache: 'no-store',
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Сервер временно недоступен.');
  }
  if (response.headers.get('content-type')?.includes('application/json')) {
    const body = await response.json() as { info: Record<string, unknown> };
    return { type: 'info', text: friendlyInfo(action, body.info) };
  }
  const blob = await response.blob();
  const extension = outputExtension[action];
  if (!extension || blob.size === 0) throw new Error('Сервер вернул пустой или неожиданный файл.');
  const base = file.name.replace(/\.[^.]+$/, '').slice(0, 70) || 'file';
  return { type: 'file', blob, name: `${base}_fileshape.${extension}` };
}

export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
