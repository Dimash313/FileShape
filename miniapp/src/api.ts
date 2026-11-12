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


export type UploadProgress = { stage: 'upload' | 'processing'; percent: number | null };
export type ProgressCallback = (progress: UploadProgress) => void;

async function postFiles(
  endpoint: string,
  form: FormData,
  onProgress?: ProgressCallback,
): Promise<{ blob: Blob; contentType: string }> {
  const signed = telegramInitData();
  if (!signed) throw new Error('Для серверных инструментов открой FileShape через Telegram.');
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', endpoint);
    xhr.timeout = 180_000;
    xhr.responseType = 'blob';
    xhr.setRequestHeader('X-Telegram-Init-Data', signed);
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.({ stage: 'upload', percent: Math.min(100, Math.round(100 * event.loaded / event.total)) });
      } else {
        onProgress?.({ stage: 'upload', percent: null });
      }
    };
    xhr.upload.onload = () => onProgress?.({ stage: 'processing', percent: null });
    xhr.onerror = () => reject(new Error('Не удалось соединиться с сервером.'));
    xhr.ontimeout = () => reject(new Error('Сервер не ответил за отведённое время.'));
    xhr.onabort = () => reject(new Error('Запрос отменён.'));
    xhr.onload = async () => {
      const blob = xhr.response as Blob;
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = 'Сервер временно недоступен.';
        try {
          const data = JSON.parse(await blob.text()) as { detail?: unknown };
          if (typeof data.detail === 'string') detail = data.detail;
        } catch { /* Fallback error message above */ }
        reject(new Error(detail));
        return;
      }
      resolve({ blob, contentType: xhr.getResponseHeader('Content-Type') ?? '' });
    };
    onProgress?.({ stage: 'upload', percent: null });
    xhr.send(form);
  });
}

export async function runServerAction(
  file: File, action: string, pages: string, onProgress?: ProgressCallback,
): Promise<ServerResult> {
  const data = new FormData();
  data.append('upload', file, file.name);
  data.append('action', action);
  if (pages) data.append('pages', pages);
  const { blob, contentType } = await postFiles('/api/v1/convert', data, onProgress);
  if (contentType.includes('application/json')) {
    const body = JSON.parse(await blob.text()) as { info: Record<string, unknown> };
    return { type: 'info', text: friendlyInfo(action, body.info) };
  }
  const extension = outputExtension[action];
  if (!extension || blob.size === 0) throw new Error('Сервер вернул пустой или неожиданный файл.');
  const base = file.name.replace(/\.[^.]+$/, '').slice(0, 70) || 'file';
  return { type: 'file', blob, name: base + '_fileshape.' + extension };
}

export async function runMultiImagePdf(files: File[], onProgress?: ProgressCallback): Promise<ServerResult> {
  if (files.length < 2 || files.length > 8) throw new Error('Выбери от 2 до 8 фотографий.');
  if (files.reduce((total, file) => total + file.size, 0) > 20 * 1024 * 1024) {
    throw new Error('Общий размер фотографий не должен превышать 20 МБ.');
  }
  const form = new FormData();
  files.forEach(file => form.append('uploads', file, file.name));
  const { blob, contentType } = await postFiles('/api/v1/images/pdf', form, onProgress);
  if (!contentType.includes('application/pdf') || blob.size === 0) {
    throw new Error('Сервер не вернул PDF.');
  }
  return { type: 'file', blob, name: 'fileshape_photos.pdf' };
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
