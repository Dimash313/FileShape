import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine } from 'lucide-react';
import { actionsFor, createBackgroundJob, getBackgroundResult, getJobStatus, getVerifiedOwner, JobApiError } from './api';
import type { JobStatus, ProgressCallback, ServerResult } from './api';
import { telegramInitData } from './telegram';
import { isTerminal, startJobPolling } from './jobPolling';
import { clearJobRefs, loadJobRefs, saveJobRefs, type JobRef } from './jobRefs';

const labels = { queued: 'Ожидает в очереди', processing: 'Обрабатывается', completed: 'Обработка завершена', failed: 'Ошибка обработки', cancelled: 'Задание отменено' };
function actionLabel(action: string) {
  return Object.values(actionsFor).flat().find(item => item.code === action)?.label ?? 'Серверная операция';
}
function deviceStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

export function useBackgroundJobs(onResult: (result: ServerResult) => void) {
  const [owner, setOwner] = useState<number | null>(null);
  const [ownerRetry, setOwnerRetry] = useState(0);
  const [ownerLoading, setOwnerLoading] = useState(false);
  const [ownerError, setOwnerError] = useState('');
  const [refs, setRefs] = useState<JobRef[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, JobStatus>>({});
  const [unavailable, setUnavailable] = useState<Record<string, boolean>>({});
  const [pollNotice, setPollNotice] = useState('');
  const [limited, setLimited] = useState(false);
  const [referenceNotice, setReferenceNotice] = useState('');
  const [resultLoading, setResultLoading] = useState(false);
  const [resultError, setResultError] = useState('');
  const [creating, setCreating] = useState(false);
  const pollerRef = useRef<ReturnType<typeof startJobPolling> | null>(null);
  const statusesRef = useRef(statuses);
  const uploadController = useRef<AbortController | null>(null);
  const resultController = useRef<AbortController | null>(null);
  statusesRef.current = statuses;
  const selected = refs.find(item => item.jobId === selectedId);
  const status = selectedId ? statuses[selectedId] : undefined;
  const active = Boolean(selected && (!status || !isTerminal(status.state)) && !unavailable[selected.jobId]);

  useEffect(() => {
    let disposed = false;
    let pending = false;
    let verified = false;
    let lastAttempt = -Infinity;
    const controller = new AbortController();
    setOwner(null); setRefs([]); setSelectedId(null); setStatuses({}); setUnavailable({});
    async function restore() {
      if (disposed || pending || verified || !telegramInitData() || document.hidden || !navigator.onLine || Date.now() - lastAttempt < 10_000) return;
      pending = true; lastAttempt = Date.now(); setOwnerLoading(true); setOwnerError('');
      try {
        const user = await getVerifiedOwner(controller.signal);
        if (disposed || controller.signal.aborted) return;
        const storage = deviceStorage();
        const saved = storage ? loadJobRefs(storage, user, Date.now() / 1000) : [];
        verified = true;
        setRefs(saved); setSelectedId(saved[0]?.jobId ?? null); setOwner(user);
        if (!storage) setReferenceNotice('Хранилище устройства недоступно. Восстановление после закрытия может не работать.');
      } catch (error) {
        if (!disposed) setOwnerError(error instanceof Error ? error.message : 'Не удалось подтвердить сессию.');
      } finally { pending = false; if (!disposed) setOwnerLoading(false); }
    }
    void restore();
    window.addEventListener('online', restore);
    document.addEventListener('visibilitychange', restore);
    return () => { disposed = true; controller.abort(); window.removeEventListener('online', restore); document.removeEventListener('visibilitychange', restore); };
  }, [ownerRetry]);

  useEffect(() => {
    if (owner === null) return;
    const storage = deviceStorage();
    if (!storage || !saveJobRefs(storage, owner, refs, Date.now() / 1000)) {
      setReferenceNotice('Ссылки доступны в этой сессии. Устройство не разрешило сохранить их для повторного открытия.');
    }
  }, [owner, refs]);

  // Dropped/expired links must not leave unbounded status IDs in memory.
  useEffect(() => {
    const ids = new Set(refs.map(item => item.jobId));
    setStatuses(items => {
      const retained = Object.entries(items).filter(([id]) => ids.has(id));
      return retained.length === Object.keys(items).length ? items : Object.fromEntries(retained);
    });
    setUnavailable(items => {
      const retained = Object.entries(items).filter(([id]) => ids.has(id));
      return retained.length === Object.keys(items).length ? items : Object.fromEntries(retained);
    });
  }, [refs]);

  useEffect(() => {
    if (!refs.length) return;
    const nextExpiry = Math.min(...refs.map(item => item.createdAt * 1000 + 3_600_000));
    const timer = window.setTimeout(() => {
      const remaining = refs.filter(item => Date.now() / 1000 - item.createdAt < 3600);
      setRefs(remaining);
      if (!remaining.some(item => item.jobId === selectedId)) setSelectedId(remaining[0]?.jobId ?? null);
    }, Math.max(0, nextExpiry - Date.now()));
    return () => window.clearTimeout(timer);
  }, [refs, selectedId]);

  useEffect(() => {
    if (owner === null || !selectedId) return;
    setPollNotice(''); setLimited(false); setResultError('');
    const known = statusesRef.current[selectedId];
    if (known && isTerminal(known.state)) return;
    const poller = startJobPolling({
      jobId: selectedId,
      request: signal => getJobStatus(selectedId, signal),
      available: () => !document.hidden && navigator.onLine,
      onStatus: next => {
        setStatuses(items => ({ ...items, [next.job_id]: next }));
        setRefs(items => items.map(item => item.jobId === next.job_id ? { ...item, updatedAt: next.updated_at } : item));
      },
      onNotice: setPollNotice,
      onStop: reason => {
        if (reason === 'limit') setLimited(true);
        if (reason === 'terminal-error') setUnavailable(items => ({ ...items, [selectedId]: true }));
      },
    });
    pollerRef.current = poller;
    const changed = () => poller.availabilityChanged();
    document.addEventListener('visibilitychange', changed);
    window.addEventListener('online', changed); window.addEventListener('offline', changed);
    return () => {
      poller.dispose();
      if (pollerRef.current === poller) pollerRef.current = null;
      document.removeEventListener('visibilitychange', changed);
      window.removeEventListener('online', changed); window.removeEventListener('offline', changed);
    };
  }, [owner, selectedId]);
  useEffect(() => () => { uploadController.current?.abort(); resultController.current?.abort(); }, []);

  async function create(file: File, action: string, pages: string, onProgress: ProgressCallback) {
    if (owner === null || active || creating) throw new Error('Подтверди сессию и дождись текущего задания либо убери его ссылку.');
    const controller = new AbortController();
    uploadController.current = controller; setCreating(true);
    try {
      const next = await createBackgroundJob(file, action, pages, onProgress, controller.signal);
      if (controller.signal.aborted) return;
      const ref = { jobId: next.job_id, action, createdAt: next.created_at, updatedAt: next.updated_at };
      setRefs(items => [ref, ...items.filter(item => item.jobId !== ref.jobId)].slice(0, 12));
      setStatuses(items => ({ ...items, [next.job_id]: next })); setSelectedId(next.job_id); setResultError('');
    } finally {
      if (uploadController.current === controller) uploadController.current = null;
      setCreating(false);
    }
  }
  async function download() {
    if (!selected || status?.state !== 'completed' || resultLoading || unavailable[selected.jobId]) return;
    const ref = selected;
    const controller = new AbortController();
    resultController.current = controller; setResultLoading(true); setResultError('');
    try {
      const result = await getBackgroundResult(ref.jobId, ref.action, controller.signal);
      if (!controller.signal.aborted) onResult(result);
    } catch (error) {
      if (!controller.signal.aborted) {
        setResultError(error instanceof Error ? error.message : 'Не удалось скачать результат.');
        if (error instanceof JobApiError && error.status === 404) setUnavailable(items => ({ ...items, [ref.jobId]: true }));
      }
    } finally {
      if (resultController.current === controller) resultController.current = null;
      setResultLoading(false);
    }
  }
  function forget() {
    if (creating || owner === null) return;
    pollerRef.current?.dispose(); resultController.current?.abort();
    const storage = deviceStorage(); if (storage) clearJobRefs(storage, owner);
    setRefs([]); setSelectedId(null); setStatuses({}); setUnavailable({}); setPollNotice('');
    setReferenceNotice('Ссылки убраны с устройства. Это не отменяет задания сервера.');
  }
  return { owner, ownerLoading, ownerError, refs, selected, status, active, creating,
    unavailable, pollNotice, limited, referenceNotice, resultLoading, resultError,
    canSubmit: owner !== null && !active && !creating, create, download, forget,
    verify: () => setOwnerRetry(value => value + 1),
    refresh: () => { setLimited(false); pollerRef.current?.refresh(); }, select: setSelectedId };
}

export function BackgroundJobsPanel({ jobs, busy }: { jobs: ReturnType<typeof useBackgroundJobs>; busy: boolean }) {
  if (!telegramInitData()) return null;
  return <section className="background-jobs" aria-label="Фоновые задания">
    <div className="section-head"><h2>Задания сервера</h2>{jobs.refs.length > 0 && <button type="button" className="text-button" disabled={busy || jobs.resultLoading} onClick={jobs.forget}>Убрать ссылки</button>}</div>
    {jobs.ownerLoading && <p role="status">Подтверждаем сессию Telegram…</p>}
    {jobs.ownerError && <p className="queue-error" role="alert">{jobs.ownerError}</p>}
    {jobs.owner === null && !jobs.ownerLoading && <button type="button" className="secondary-button full" onClick={jobs.verify}>Подтвердить сессию</button>}
    {jobs.selected ? <>
      <div className="background-job-state" role="status" aria-live="polite">
        <strong>{jobs.status ? labels[jobs.status.state] : 'Проверяем сохранённое задание'}</strong>
        <span>{actionLabel(jobs.selected.action)}</span>
        {jobs.pollNotice && <p>{jobs.pollNotice}</p>}
        {jobs.status?.state === 'queued' && <p>Задание принято и ожидает свободного обработчика.</p>}
        {jobs.status?.state === 'processing' && <p>Дождись завершения обработки.</p>}
        {jobs.status?.state === 'failed' && <p>Сервер сообщил об ошибке обработки. Готового результата нет.</p>}
        {jobs.status?.state === 'cancelled' && <p>Сервер подтвердил отмену. Результат недоступен.</p>}
        {jobs.status?.state === 'completed' && <p>Обработка завершена. Скачивание доступно, пока временный результат не удалён.</p>}
      </div>
      {jobs.status?.state === 'completed' && <button type="button" className="primary-button full" disabled={jobs.resultLoading || jobs.unavailable[jobs.selected.jobId]} onClick={() => void jobs.download()}>{jobs.resultLoading ? 'Получаем результат…' : jobs.selected.action.endsWith(':info') || jobs.selected.action === 'zip:list' ? 'Посмотреть результат' : 'Скачать результат'} <ArrowDownToLine size={17}/></button>}
      {!jobs.status || !isTerminal(jobs.status.state) ? <button type="button" className="secondary-button full" disabled={Boolean(jobs.unavailable[jobs.selected.jobId])} onClick={jobs.refresh}>{jobs.limited ? 'Продолжить проверку статуса' : 'Проверить статус'}</button> : null}
      {jobs.resultError && <p className="queue-error" role="alert">{jobs.resultError}</p>}
    </> : jobs.owner !== null && <p>Здесь появятся принятые задания. Закрытие Mini App не отменяет подтверждённую сервером обработку.</p>}
    {jobs.refs.length > 1 && <div className="saved-job-links" aria-label="Сохранённые задания">{jobs.refs.map(item => <button type="button" key={item.jobId} disabled={jobs.resultLoading} aria-pressed={jobs.selected?.jobId === item.jobId} onClick={() => jobs.select(item.jobId)}>{actionLabel(item.action)} · {new Date(item.createdAt * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</button>)}</div>}
    {jobs.referenceNotice && <p className="transfer-wait">{jobs.referenceNotice}</p>}
    <small>До 12 ссылок. Через час с принятия они перестают восстанавливаться и удаляются при работе приложения или следующем открытии. Сохраняются только подтверждённые номера заданий. Очистка ссылок не удаляет данные сервера.</small>
  </section>;
}
