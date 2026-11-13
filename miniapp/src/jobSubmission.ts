/** One in-memory upload intent. Files and idempotency keys never enter storage. */
export type Submission = {
  file: File;
  action: string;
  pages: string;
  retryOf?: string;
  key: string;
  acceptedJobId?: string;
};

type CryptoSource = {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => unknown;
};

export function createIdempotencyKey(source: CryptoSource | undefined = globalThis.crypto): string {
  if (typeof source?.randomUUID === 'function') {
    try {
      const value = source.randomUUID();
      if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) return value;
    } catch {
      // Some WebViews expose randomUUID but require getRandomValues instead.
    }
  }
  if (typeof source?.getRandomValues !== 'function') {
    throw new Error('Устройство не поддерживает безопасную отправку. Открой Mini App в обновлённом Telegram.');
  }
  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

function validFile(file: File): boolean {
  return file instanceof File && file.size > 0 && file.size <= 20 * 1024 * 1024;
}

export class SubmissionKeeper {
  current: Submission | null = null;
  constructor(private readonly keyFactory: () => string = createIdempotencyKey) {}

  prepare(file: File, action: string, pages: string, retryOf?: string): Submission {
    if (!validFile(file)) throw new Error('Выбери непустой файл размером до 20 МБ.');
    const previous = this.current;
    if (previous && previous.acceptedJobId === undefined && previous.file === file &&
        previous.action === action && previous.pages === pages && previous.retryOf === retryOf) return previous;
    const next: Submission = { file, action, pages, key: this.keyFactory() };
    if (retryOf !== undefined) next.retryOf = retryOf;
    this.current = next;
    return next;
  }

  accept(descriptor: Submission, jobId: string): void {
    // A late response for a replaced intent must never attach its ID to a new file.
    if (this.current !== descriptor || descriptor.acceptedJobId !== undefined) return;
    if (!/^[A-Za-z0-9_-]{32}$/.test(jobId)) throw new Error('Не удалось подтвердить номер задания.');
    descriptor.acceptedJobId = jobId;
  }

  retrySource(jobId: string): Submission | null {
    return this.current?.acceptedJobId === jobId && validFile(this.current.file) ? this.current : null;
  }

  clear(): void {
    this.current = null;
  }
}

/** Validate retry ranges without assuming the page count of a reselected PDF. */
export function retryPagesAreValid(action: string, pages: string): boolean {
  if (action !== 'pdf:extract' && action !== 'pdf:remove') return true;
  if (!pages.trim() || pages.length > 90) return false;
  const selected = new Set<number>();
  for (const part of pages.split(',')) {
    const match = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) return false;
    const first = Number(match[1]);
    const last = Number(match[2] ?? match[1]);
    if (first < 1 || last > 250 || first > last) return false;
    for (let page = first; page <= last; page += 1) {
      selected.add(page);
      if (selected.size > 150) return false;
    }
  }
  return true;
}
