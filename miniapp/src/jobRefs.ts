/** Short-lived links only: no names, files, results or Telegram launch data. */
export type JobRef = {
  jobId: string;
  action: string;
  createdAt: number;
  updatedAt: number;
};

type RefStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const MAX_REFS = 12;
const TTL_SECONDS = 3600;
const MAX_JSON_BYTES = 16 * 1024;
const JOB_ID = /^[A-Za-z0-9_-]{32}$/;
const ACTIONS = new Set([
  'img:JPEG', 'img:PNG', 'img:WEBP', 'img:PDF', 'img:compress',
  'pdf:rotate', 'pdf:first', 'pdf:extract', 'pdf:remove', 'pdf:info',
  'audio:mp3', 'audio:ogg', 'audio:wav', 'audio:info',
  'docx:txt', 'docx:info', 'txt:docx', 'txt:info', 'zip:list',
]);

function storageKey(owner: number): string | null {
  return Number.isSafeInteger(owner) && owner > 0 ? `fileshape:jobs:v43:${owner}` : null;
}

function validTime(now: number): boolean {
  return Number.isFinite(now) && now > 0;
}

function normalize(input: unknown, now: number): JobRef[] {
  if (!Array.isArray(input)) return [];
  const valid: JobRef[] = [];
  // UI callers keep at most 12 references; also bound malformed input callers.
  for (const value of input.slice(0, 1000)) {
    if (typeof value !== 'object' || value === null) continue;
    const item = value as Record<string, unknown>;
    if (typeof item.jobId !== 'string' || !JOB_ID.test(item.jobId) ||
        typeof item.action !== 'string' || !ACTIONS.has(item.action) ||
        typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt) ||
        typeof item.updatedAt !== 'number' || !Number.isFinite(item.updatedAt) ||
        item.createdAt <= 0 || item.updatedAt < item.createdAt ||
        item.createdAt > now + 30 || item.updatedAt > now + 30 ||
        now - item.createdAt >= TTL_SECONDS) continue;
    // Deliberately construct a new object so unknown/private properties vanish.
    valid.push({ jobId: item.jobId, action: item.action,
      createdAt: item.createdAt, updatedAt: item.updatedAt });
  }
  valid.sort((left, right) => right.createdAt - left.createdAt || right.updatedAt - left.updatedAt);
  const seen = new Set<string>();
  return valid.filter(item => {
    if (seen.has(item.jobId)) return false;
    seen.add(item.jobId);
    return true;
  }).slice(0, MAX_REFS);
}

function write(storage: RefStorage, key: string, refs: JobRef[]): boolean {
  try {
    if (refs.length) storage.setItem(key, JSON.stringify(refs));
    else storage.removeItem(key);
    return true;
  } catch {
    // A WebView can deny storage without preventing current-session jobs.
    return false;
  }
}

export function loadJobRefs(storage: RefStorage, owner: number, nowSeconds: number): JobRef[] {
  const key = storageKey(owner);
  if (key === null || !validTime(nowSeconds)) return [];
  let parsed: unknown;
  try {
    const raw = storage.getItem(key);
    if (raw === null) return [];
    if (typeof raw !== 'string' || raw.length > MAX_JSON_BYTES ||
        new TextEncoder().encode(raw).byteLength > MAX_JSON_BYTES) {
      write(storage, key, []);
      return [];
    }
    parsed = JSON.parse(raw);
  } catch {
    write(storage, key, []);
    return [];
  }
  const refs = normalize(parsed, nowSeconds);
  // Expired entries and unknown properties are removed from storage on access.
  write(storage, key, refs);
  return refs;
}

export function saveJobRefs(storage: RefStorage, owner: number, refs: JobRef[], nowSeconds: number): boolean {
  const key = storageKey(owner);
  if (key === null || !validTime(nowSeconds)) return false;
  return write(storage, key, normalize(refs, nowSeconds));
}

export function clearJobRefs(storage: RefStorage, owner: number): boolean {
  const key = storageKey(owner);
  return key !== null && write(storage, key, []);
}
