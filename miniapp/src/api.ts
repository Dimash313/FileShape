import { telegramInitData } from './telegram.js';
import { createIdempotencyKey } from './jobSubmission.js';

export type QueueStatus = {
  capacity: number;
  active: number;
  waiting: number;
  waiting_limit: number;
  accepting: boolean;
};

export async function getQueueStatus(): Promise<QueueStatus> {
  const signed = telegramInitData();
  if (!signed) throw new Error('Открой приложение внутри Telegram, чтобы проверить очередь.');
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8_000);
  try {
    reserveRequest();
    const response = await fetch('/api/v1/queue', {
      headers: { 'X-Telegram-Init-Data': signed },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) throw new Error('Не удалось получить нагрузку сервера. Попробуй позже.');
    const status = await response.json() as QueueStatus;
    if (
      !Number.isInteger(status.capacity) || status.capacity < 1 ||
      !Number.isInteger(status.active) || status.active < 0 || status.active > status.capacity ||
      !Number.isInteger(status.waiting) || status.waiting < 0 ||
      !Number.isInteger(status.waiting_limit) || status.waiting_limit < 0 ||
      typeof status.accepting !== 'boolean'
    ) throw new Error('Сервер вернул некорректный статус очереди.');
    return status;
  } finally {
    window.clearTimeout(timeout);
  }
}

export type JobStatus = {
  job_id: string;
  state: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
  created_at: number;
  updated_at: number;
};

export class JobApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
  get terminal() { return this.status === 401 || this.status === 404; }
}

// Leave room beneath the server's shared 12/minute limit. This budget also
// covers manual controls, restored jobs and the legacy conversion endpoints.
const requestTimes: number[] = [];
let lastStatusRequest = -Infinity;
function reserveRequest(status = false) {
  const now = performance.now();
  while (requestTimes.length && now - requestTimes[0] >= 60_000) requestTimes.shift();
  if (requestTimes.length >= 10 || (status && now - lastStatusRequest < 10_000)) {
    throw new JobApiError(429, 'Следующая проверка доступна чуть позже. Подожди несколько секунд.');
  }
  requestTimes.push(now);
  if (status) lastStatusRequest = now;
}

function requestController(signal?: AbortSignal, timeoutMs = 8_000) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = window.setTimeout(abort, timeoutMs);
  return { controller, cleanup() { window.clearTimeout(timeout); signal?.removeEventListener('abort', abort); controller.abort(); } };
}

export function validateJobStatus(value: unknown, expectedId?: string): JobStatus {
  const data = value as JobStatus | null;
  if (!data || typeof data !== 'object' || typeof data.job_id !== 'string' ||
      !/^[A-Za-z0-9_-]{32}$/.test(data.job_id) || (expectedId && data.job_id !== expectedId) ||
      !['queued', 'processing', 'completed', 'failed', 'cancelled'].includes(data.state) ||
      !Number.isFinite(data.created_at) || !Number.isFinite(data.updated_at) ||
      data.created_at <= 0 || data.updated_at < data.created_at || data.updated_at > Date.now() / 1000 + 60) {
    throw new Error('Некорректный ответ сервера.');
  }
  return { job_id: data.job_id, state: data.state, created_at: data.created_at, updated_at: data.updated_at };
}

export async function getVerifiedOwner(signal?: AbortSignal): Promise<number> {
  const signed = telegramInitData();
  if (!signed) throw new JobApiError(401, 'Открой приложение внутри Telegram.');
  const request = requestController(signal);
  try {
    const response = await fetch('/api/v1/session', {
      headers: { 'X-Telegram-Init-Data': signed }, cache: 'no-store', signal: request.controller.signal,
    });
    if (!response.ok) throw new JobApiError(response.status, 'Не удалось подтвердить сессию Telegram. Открой Mini App заново.');
    const data = await response.json() as { user_id?: number; ok?: boolean };
    if (data.ok !== true || !Number.isSafeInteger(data.user_id) || (data.user_id ?? 0) <= 0) throw new Error('Некорректная сессия сервера.');
    return data.user_id!;
  } finally { request.cleanup(); }
}

export async function getJobStatus(jobId: string, signal?: AbortSignal): Promise<JobStatus> {
  if (!/^[A-Za-z0-9_-]{32}$/.test(jobId)) throw new Error('Некорректный идентификатор задания.');
  const signed = telegramInitData();
  if (!signed) throw new JobApiError(401, 'Открой приложение внутри Telegram.');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  reserveRequest(true);
  const request = requestController(signal);
  try {
    const response = await fetch('/api/v1/jobs/' + encodeURIComponent(jobId), {
      headers: { 'X-Telegram-Init-Data': signed }, cache: 'no-store', signal: request.controller.signal,
    });
    if (response.status === 404) throw new JobApiError(404, 'Задание больше не доступно на сервере.');
    if (response.status === 401) throw new JobApiError(401, 'Сессия Telegram устарела. Открой Mini App заново.');
    if (!response.ok) throw new JobApiError(response.status, 'Не удалось проверить задание. Последний подтверждённый статус сохранён.');
    return validateJobStatus(await response.json(), jobId);
  } finally { request.cleanup(); }
}

export type ServerAction = { code: string; label: string; pages?: boolean };
export type ServerResult = { type: 'info'; text: string; jobId?: string } | { type: 'file'; blob: Blob; name: string; jobId?: string };

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
  'img:JPEG': 'jpg', 'img:PNG': 'png', 'img:WEBP': 'webp', 'img:PDF': 'pdf', 'img:compress': 'webp',
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


export type UploadProgress = { stage: 'upload' | 'validation' | 'processing'; percent: number | null };
export type ProgressCallback = (progress: UploadProgress) => void;

async function postFiles(
  endpoint: string,
  form: FormData,
  onProgress?: ProgressCallback,
  background = false,
  signal?: AbortSignal,
  idempotencyKey?: string,
): Promise<{ blob: Blob; contentType: string; jobId?: string }> {
  const signed = telegramInitData();
  if (!signed) throw new Error('Для серверных инструментов открой FileShape через Telegram.');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  reserveRequest();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener('abort', abort);
    const fail = (error: Error) => { cleanup(); reject(error); };
    xhr.open('POST', endpoint);
    xhr.timeout = 180_000;
    xhr.responseType = 'blob';
    xhr.setRequestHeader('X-Telegram-Init-Data', signed);
    if (idempotencyKey) xhr.setRequestHeader('Idempotency-Key', idempotencyKey);
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.({ stage: 'upload', percent: Math.min(100, Math.round(100 * event.loaded / event.total)) });
      } else {
        onProgress?.({ stage: 'upload', percent: null });
      }
    };
    xhr.upload.onload = () => onProgress?.({ stage: background ? 'validation' : 'processing', percent: null });
    xhr.onerror = () => fail(new Error(background ? 'Связь прервана. Сервер мог принять файл, но номер задания не получен. Автоматическая повторная отправка не выполняется.' : 'Не удалось соединиться с сервером.'));
    xhr.ontimeout = () => fail(new Error('Сервер не ответил за отведённое время. Номер задания не подтверждён.'));
    xhr.onabort = () => fail(new DOMException('Запрос прерван.', 'AbortError'));
    xhr.onload = async () => {
      const blob = xhr.response as Blob;
      if (xhr.status < 200 || xhr.status >= 300 || (background && xhr.status !== 202)) {
        let detail = 'Сервер временно недоступен.';
        try {
          const data = JSON.parse(await blob.text()) as { detail?: unknown };
          if (typeof data.detail === 'string') detail = data.detail;
        } catch { /* Fallback error message above */ }
        fail(new JobApiError(xhr.status, detail));
        return;
      }
      cleanup();
      const jobId = xhr.getResponseHeader('X-FileShape-Job-Id') ?? undefined;
      resolve({ blob, contentType: xhr.getResponseHeader('Content-Type') ?? '', jobId });
    };
    onProgress?.({ stage: 'upload', percent: null });
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) { fail(new DOMException('Aborted', 'AbortError')); return; }
    xhr.send(form);
  });
}

export async function createBackgroundJob(
  file: File, action: string, pages: string, onProgress?: ProgressCallback, signal?: AbortSignal,
  idempotencyKey: string = createIdempotencyKey(),
): Promise<JobStatus> {
  validateSubmissionKey(idempotencyKey);
  const form = new FormData();
  form.append('upload', file, file.name);
  form.append('action', action);
  if (pages) form.append('pages', pages);
  const { blob, contentType } = await postFiles('/api/v1/jobs', form, onProgress, true, signal, idempotencyKey);
  if (!contentType.includes('application/json') || blob.size > 65536) throw new Error('Не удалось подтвердить номер задания.');
  return validateJobStatus(JSON.parse(await blob.text()));
}

function validateSubmissionKey(value: string) {
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(value)) throw new Error('Некорректное подтверждение отправки.');
}

export async function cancelBackgroundJob(jobId: string, signal?: AbortSignal): Promise<JobStatus> {
  if (!/^[A-Za-z0-9_-]{32}$/.test(jobId)) throw new Error('Некорректный идентификатор задания.');
  const signed = telegramInitData();
  if (!signed) throw new JobApiError(401, 'Открой приложение внутри Telegram.');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  reserveRequest();
  const request = requestController(signal, 125_000);
  try {
    const response = await fetch('/api/v1/jobs/' + encodeURIComponent(jobId) + '/cancel', {
      method: 'POST', headers: { 'X-Telegram-Init-Data': signed }, cache: 'no-store', signal: request.controller.signal,
    });
    if (response.status === 401) throw new JobApiError(401, 'Сессия Telegram устарела. Открой Mini App заново.');
    if (response.status === 404) throw new JobApiError(404, 'Задание недоступно. Отмена не подтверждена.');
    if (response.status !== 200) throw new JobApiError(response.status, 'Сервер не подтвердил отмену. Проверка статуса продолжится.');
    return validateJobStatus(await response.json(), jobId);
  } finally { request.cleanup(); }
}

export async function retryBackgroundJob(
  jobId: string, file: File, action: string, pages: string, idempotencyKey: string,
  onProgress?: ProgressCallback, signal?: AbortSignal,
): Promise<JobStatus> {
  if (!/^[A-Za-z0-9_-]{32}$/.test(jobId)) throw new Error('Некорректный идентификатор задания.');
  validateSubmissionKey(idempotencyKey);
  const form = new FormData();
  form.append('upload', file, file.name); form.append('action', action);
  if (pages) form.append('pages', pages);
  const { blob, contentType } = await postFiles('/api/v1/jobs/' + encodeURIComponent(jobId) + '/retry', form, onProgress, true, signal, idempotencyKey);
  if (!contentType.includes('application/json') || blob.size > 65536) throw new Error('Не удалось подтвердить номер повторного задания.');
  return validateJobStatus(JSON.parse(await blob.text()));
}

export async function getBackgroundResult(jobId: string, action: string, signal?: AbortSignal): Promise<ServerResult> {
  if (!/^[A-Za-z0-9_-]{32}$/.test(jobId)) throw new Error('Некорректный идентификатор задания.');
  const signed = telegramInitData();
  if (!signed) throw new JobApiError(401, 'Открой приложение внутри Telegram.');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  reserveRequest();
  const request = requestController(signal, 125_000);
  try {
    const response = await fetch('/api/v1/jobs/' + encodeURIComponent(jobId) + '/result', {
      headers: { 'X-Telegram-Init-Data': signed }, cache: 'no-store', signal: request.controller.signal,
    });
    if (response.status === 404) throw new JobApiError(404, 'Результат удалён по сроку хранения или после перезапуска сервера.');
    if (response.status === 401) throw new JobApiError(401, 'Сессия Telegram устарела. Открой Mini App заново.');
    if (!response.ok) throw new JobApiError(response.status, 'Не удалось получить результат. Попробуй позже.');
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > 45 * 1024 * 1024) throw new Error('Результат превышает допустимый размер.');
    const parts: BlobPart[] = [];
    let received = 0;
    const reader = response.body?.getReader();
    let blob: Blob;
    if (reader) {
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          received += chunk.value.byteLength;
          if (received > 45 * 1024 * 1024) { await reader.cancel(); throw new Error('Результат превышает допустимый размер.'); }
          parts.push(chunk.value);
        }
      } finally { reader.releaseLock(); }
      blob = new Blob(parts, { type: response.headers.get('content-type') ?? '' });
    } else blob = await response.blob();
    if (!blob.size || blob.size > 45 * 1024 * 1024) throw new Error('Сервер вернул пустой или слишком большой результат.');
    if ((response.headers.get('content-type') ?? '').includes('application/json')) {
      if (blob.size > 65536) throw new Error('Информация о файле слишком большая.');
      const data = JSON.parse(await blob.text()) as { info?: Record<string, unknown> };
      if (!data.info || typeof data.info !== 'object' || Array.isArray(data.info)) throw new Error('Некорректная информация о файле.');
      return { type: 'info', text: friendlyInfo(action, data.info), jobId };
    }
    const extension = outputExtension[action];
    if (!extension) throw new Error('Неожиданный формат результата.');
    return { type: 'file', blob, name: 'fileshape_result.' + extension, jobId };
  } finally { request.cleanup(); }
}

export async function runServerAction(
  file: File, action: string, pages: string, onProgress?: ProgressCallback,
): Promise<ServerResult> {
  const data = new FormData();
  data.append('upload', file, file.name);
  data.append('action', action);
  if (pages) data.append('pages', pages);
  const { blob, contentType, jobId } = await postFiles('/api/v1/convert', data, onProgress);
  if (contentType.includes('application/json')) {
    const body = JSON.parse(await blob.text()) as { info: Record<string, unknown> };
    return { type: 'info', text: friendlyInfo(action, body.info), jobId };
  }
  const extension = outputExtension[action];
  if (!extension || blob.size === 0) throw new Error('Сервер вернул пустой или неожиданный файл.');
  const base = file.name.replace(/\.[^.]+$/, '').slice(0, 70) || 'file';
  return { type: 'file', blob, name: base + '_fileshape.' + extension, jobId };
}

export async function runMultiImagePdf(files: File[], onProgress?: ProgressCallback): Promise<ServerResult> {
  if (files.length < 2 || files.length > 8) throw new Error('Выбери от 2 до 8 фотографий.');
  if (files.reduce((total, file) => total + file.size, 0) > 20 * 1024 * 1024) {
    throw new Error('Общий размер фотографий не должен превышать 20 МБ.');
  }
  const form = new FormData();
  files.forEach(file => form.append('uploads', file, file.name));
  const { blob, contentType, jobId } = await postFiles('/api/v1/images/pdf', form, onProgress);
  if (!contentType.includes('application/pdf') || blob.size === 0) {
    throw new Error('Сервер не вернул PDF.');
  }
  return { type: 'file', blob, name: 'fileshape_photos.pdf', jobId };
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
