import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine } from 'lucide-react';
import { actionsFor, cancelBackgroundJob, createBackgroundJob, retryBackgroundJob, getBackgroundResult, getJobStatus, getVerifiedOwner, JobApiError } from './api';
import type { JobStatus, ProgressCallback, ServerResult } from './api';
import { telegramInitData } from './telegram';
import { isTerminal, startJobPolling } from './jobPolling';
import { clearJobRefs, loadJobRefs, saveJobRefs, type JobRef } from './jobRefs';
import { SubmissionKeeper, retryPagesAreValid, type Submission } from './jobSubmission';

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
  const [cancelling, setCancelling] = useState(false);
  const [controlError, setControlError] = useState('');
  const [controlNotice, setControlNotice] = useState('');
  const [watchEpoch, setWatchEpoch] = useState(0);
  const [submissionRevision, setSubmissionRevision] = useState(0);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [retryPages, setRetryPages] = useState('');
  const [retryProgress, setRetryProgress] = useState<Parameters<ProgressCallback>[0] | null>(null);
  const keeper = useRef(new SubmissionKeeper());
  const inputDeadline = useRef(0);
  const deferredInputRelease = useRef(false);
  const selectedIdRef = useRef(selectedId);
  const controlController = useRef<AbortController | null>(null);
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
    setOwner(null); setRefs([]); selectJob(null); setStatuses({}); setUnavailable({}); releaseInput();
    async function restore() {
      if (disposed || pending || verified || !telegramInitData() || document.hidden || !navigator.onLine || Date.now() - lastAttempt < 10_000) return;
      pending = true; lastAttempt = Date.now(); setOwnerLoading(true); setOwnerError('');
      try {
        const user = await getVerifiedOwner(controller.signal);
        if (disposed || controller.signal.aborted) return;
        const storage = deviceStorage();
        const saved = storage ? loadJobRefs(storage, user, Date.now() / 1000) : [];
        verified = true;
        setRefs(saved); selectJob(saved[0]?.jobId ?? null); setOwner(user);
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
    const cached = keeper.current.current;
    if (cached && (cached.acceptedJobId ? !ids.has(cached.acceptedJobId) : cached.retryOf && !ids.has(cached.retryOf))) releaseInput();
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
      if (!remaining.some(item => item.jobId === selectedId)) selectJob(remaining[0]?.jobId ?? null);
    }, Math.max(0, nextExpiry - Date.now()));
    return () => window.clearTimeout(timer);
  }, [refs, selectedId]);

  useEffect(() => {
    if (owner === null || !selectedId || cancelling) return;
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
  }, [owner, selectedId, watchEpoch, cancelling]);
  useEffect(() => {
    setRetryPages(keeper.current.retrySource(selectedId ?? '')?.pages ?? '');
    setControlError(''); setControlNotice('');
  }, [selectedId]);
  useEffect(() => {
    const cached = keeper.current.current;
    if (!cached) return;
    const timer = window.setTimeout(() => {
      if (keeper.current.current === cached) {
        releaseInput();
        setControlNotice('Исходный файл больше не хранится в этом окне. Для повторения выбери его заново.');
      }
    }, Math.max(0, inputDeadline.current - performance.now()));
    return () => window.clearTimeout(timer);
  }, [submissionRevision]);
  useEffect(() => () => {
    uploadController.current?.abort(); resultController.current?.abort(); controlController.current?.abort(); keeper.current.clear();
  }, []);

  function selectJob(id: string | null) {
    selectedIdRef.current = id;
    setSelectedId(id);
  }
  function releaseInput() {
    if (uploadController.current !== null) { deferredInputRelease.current = true; return; }
    deferredInputRelease.current = false;
    keeper.current.clear(); inputDeadline.current = 0;
    setUnconfirmed(false); setSubmissionRevision(value => value + 1);
  }
  function prepare(file: File, action: string, pages: string, retryOf?: string) {
    const previous = keeper.current.current;
    const next = keeper.current.prepare(file, action, pages, retryOf);
    if (next !== previous) { inputDeadline.current = performance.now() + 3_600_000; setSubmissionRevision(value => value + 1); }
    return next;
  }
  async function send(descriptor: Submission, onProgress: ProgressCallback) {
    if (owner === null || creating || cancelling) throw new Error('Дождись подтверждения сессии или завершения текущего запроса.');
    const controller = new AbortController();
    uploadController.current = controller; setCreating(true); setControlError(''); setControlNotice(''); setUnconfirmed(false);
    try {
      const next = descriptor.retryOf
        ? await retryBackgroundJob(descriptor.retryOf, descriptor.file, descriptor.action, descriptor.pages, descriptor.key, onProgress, controller.signal)
        : await createBackgroundJob(descriptor.file, descriptor.action, descriptor.pages, onProgress, controller.signal, descriptor.key);
      if (controller.signal.aborted || keeper.current.current !== descriptor) throw new DOMException('Отправка прервана. Подтверждение задания не получено.', 'AbortError');
      keeper.current.accept(descriptor, next.job_id);
      const ref = { jobId: next.job_id, action: descriptor.action, createdAt: next.created_at, updatedAt: next.updated_at };
      setRefs(items => [ref, ...items.filter(item => item.jobId !== ref.jobId)].slice(0, 12));
      setStatuses(items => ({ ...items, [next.job_id]: next })); selectJob(next.job_id); setResultError('');
      setControlNotice('Задание принято сервером.'); setSubmissionRevision(value => value + 1);
    } catch (error) {
      if (!controller.signal.aborted && keeper.current.current === descriptor) {
        setUnconfirmed(true);
        setControlError(error instanceof Error ? error.message : 'Номер задания не подтверждён.');
      }
      throw error;
    } finally {
      if (uploadController.current === controller) {
        uploadController.current = null;
        if (deferredInputRelease.current || performance.now() >= inputDeadline.current) releaseInput();
      }
      setCreating(false); setRetryProgress(null);
    }
  }

  async function create(file: File, action: string, pages: string, onProgress: ProgressCallback) {
    if (owner === null || active || creating || cancelling) throw new Error('Подтверди сессию и дождись текущего задания либо убери его ссылку.');
    await send(prepare(file, action, pages), onProgress);
  }
  async function cancel() {
    if (!selected || !status || isTerminal(status.state) || owner === null || cancelling || creating) return;
    const id = selected.jobId;
    pollerRef.current?.dispose(); pollerRef.current = null;
    const controller = new AbortController(); controlController.current = controller;
    setCancelling(true); setControlError(''); setControlNotice('');
    try {
      const next = await cancelBackgroundJob(id, controller.signal);
      if (controller.signal.aborted || selectedIdRef.current !== id) return;
      setStatuses(items => ({ ...items, [id]: next }));
      setRefs(items => items.map(item => item.jobId === id ? { ...item, updatedAt: next.updated_at } : item));
      setControlNotice(next.state === 'cancelled' ? 'Сервер подтвердил отмену.' : 'Сервер вернул текущий статус. Задание могло завершиться до отмены.');
    } catch (error) {
      if (!controller.signal.aborted && selectedIdRef.current === id) setControlError((error instanceof Error ? error.message : 'Отмена не подтверждена.') + ' Последний статус сохранён; проверка продолжится.');
    } finally {
      if (controlController.current === controller) controlController.current = null;
      setCancelling(false); setWatchEpoch(value => value + 1);
    }
  }
  const retained = selected ? keeper.current.retrySource(selected.jobId) : null;
  const draft = keeper.current.current;
  const retryInput = selected && draft && !draft.acceptedJobId && draft.retryOf === selected.jobId ? draft : retained;
  const needsPages = selected?.action === 'pdf:extract' || selected?.action === 'pdf:remove';
  const retryPagesValid = retryPagesAreValid(selected?.action ?? '', retryPages);
  function chooseRetryFile(file?: File) {
    if (!file || !selected || owner === null || creating || cancelling) return;
    try { prepare(file, selected.action, retryPages.trim(), selected.jobId); setUnconfirmed(false); setControlError(''); }
    catch (error) { setControlError(error instanceof Error ? error.message : 'Выбери исходный файл заново.'); }
  }
  function updateRetryPages(value: string) {
    setRetryPages(value);
    const cached = keeper.current.current;
    if (selected && cached && !cached.acceptedJobId && cached.retryOf === selected.jobId && cached.pages !== value.trim()) {
      prepare(cached.file, cached.action, value.trim(), selected.jobId);
      setUnconfirmed(false);
    }
  }
  async function retry() {
    if (!selected || !status || !['failed', 'cancelled'].includes(status.state) || !retryInput || !retryPagesValid) return;
    try { await send(prepare(retryInput.file, selected.action, needsPages ? retryPages.trim() : '', selected.jobId), setRetryProgress); }
    catch { /* send retains the same logical request for an explicit resubmission. */ }
  }
  async function repeatUnconfirmed() {
    const descriptor = keeper.current.current;
    if (!descriptor || descriptor.acceptedJobId || !unconfirmed || creating || cancelling || owner === null) return;
    try { await send(descriptor, setRetryProgress); } catch { /* Error remains visible; never resubmit automatically. */ }
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
    if (creating || cancelling || owner === null) return;
    releaseInput();
    pollerRef.current?.dispose(); resultController.current?.abort();
    const storage = deviceStorage(); if (storage) clearJobRefs(storage, owner);
    setRefs([]); selectJob(null); setStatuses({}); setUnavailable({}); setPollNotice('');
    setReferenceNotice('Ссылки убраны с устройства. Это не отменяет задания сервера.');
  }
  return { owner, ownerLoading, ownerError, refs, selected, status, active, creating,
    unavailable, pollNotice, limited, referenceNotice, resultLoading, resultError,
    cancelling, controlError, controlNotice, retryProgress, retryInput, retryPages, needsPages, retryPagesValid,
    unconfirmed, unconfirmedAction: draft?.action, unconfirmedPages: draft?.pages, canRepeatUnconfirmed: unconfirmed && Boolean(draft && !draft.acceptedJobId),
    chooseRetryFile, setRetryPages: updateRetryPages, retry, cancel, repeatUnconfirmed, releaseInput,
    canSubmit: owner !== null && !active && !creating && !cancelling, create, download, forget,
    verify: () => setOwnerRetry(value => value + 1),
    refresh: () => { setLimited(false); pollerRef.current?.refresh(); }, select: selectJob };
}

export function BackgroundJobsPanel({ jobs, busy }: { jobs: ReturnType<typeof useBackgroundJobs>; busy: boolean }) {
  if (!telegramInitData()) return null;
  return <section className="background-jobs" aria-label="Фоновые задания">
    <div className="section-head"><h2>Задания сервера</h2>{jobs.refs.length > 0 && <button type="button" className="text-button" disabled={busy || jobs.resultLoading || jobs.creating || jobs.cancelling} onClick={jobs.forget}>Убрать ссылки</button>}</div>
    {jobs.ownerLoading && <p role="status">Подтверждаем сессию Telegram…</p>}
    {jobs.ownerError && <p className="queue-error" role="alert">{jobs.ownerError}</p>}
    {jobs.owner === null && !jobs.ownerLoading && <button type="button" className="secondary-button full" onClick={jobs.verify}>Подтвердить сессию</button>}
    {jobs.selected ? <>
      <div className={`background-job-state state-${jobs.status?.state ?? 'checking'}`} role="status" aria-live="polite">
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
      {!jobs.status || !isTerminal(jobs.status.state) ? <button type="button" className="secondary-button full" disabled={Boolean(jobs.unavailable[jobs.selected.jobId]) || jobs.cancelling} onClick={jobs.refresh}>{jobs.limited ? 'Продолжить проверку статуса' : 'Проверить статус'}</button> : null}
      {jobs.status && !isTerminal(jobs.status.state) && <button type="button" className="secondary-button full" disabled={busy || jobs.creating || jobs.cancelling || Boolean(jobs.unavailable[jobs.selected.jobId])} onClick={() => void jobs.cancel()}>{jobs.cancelling ? 'Подтверждаем отмену…' : 'Отменить задание'}</button>}
      {jobs.status && ['failed', 'cancelled'].includes(jobs.status.state) && <div className="job-retry-panel">
        <strong>Повторная обработка</strong>
        {jobs.retryInput ? <p>Исходный файл доступен в этом окне: {jobs.retryInput.file.name}</p> : <p>Исходный файл не сохранён после закрытия приложения. Выбери его заново для повторения.</p>}
        <label className="retry-file-label">Выбрать исходный файл заново<input type="file" disabled={busy || jobs.creating || jobs.cancelling} onChange={event => { jobs.chooseRetryFile(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label>
        {jobs.needsPages && <label className="pages-field">Страницы для новой попытки<input type="text" maxLength={90} value={jobs.retryPages} disabled={jobs.creating} placeholder="Например: 1,3-5" onChange={event => jobs.setRetryPages(event.target.value)} aria-invalid={!jobs.retryPagesValid} /><small>После повторного открытия выбери диапазон снова. Сервер проверит его по новому файлу.</small></label>}
        <button type="button" className="primary-button full" disabled={busy || jobs.creating || jobs.cancelling || !jobs.retryInput || !jobs.retryPagesValid} onClick={() => void jobs.retry()}>{jobs.creating ? 'Загружаем для повтора…' : 'Повторить обработку'}</button>
      </div>}
      {jobs.resultError && <p className="queue-error" role="alert">{jobs.resultError}</p>}
    </> : jobs.owner !== null && <p>Здесь появятся принятые задания. Закрытие Mini App не отменяет подтверждённую сервером обработку.</p>}
    {jobs.controlNotice && <p role="status">{jobs.controlNotice}</p>}
    {jobs.controlError && <p className="queue-error" role="alert">{jobs.controlError}</p>}
    {jobs.retryProgress && <div className="transfer-status" role="status">{jobs.retryProgress.stage === 'upload' ? `Загрузка файла${jobs.retryProgress.percent === null ? '' : ': ' + jobs.retryProgress.percent + '%'}` : 'Файл загружен, сервер проверяет его.'}</div>}
    {jobs.canRepeatUnconfirmed && <div className="unconfirmed-submission"><p>Номер задания не подтверждён. Можно вручную повторить эту же отправку с защитой от дублирования. Автоматического повтора нет.</p><p>{actionLabel(jobs.unconfirmedAction ?? '')}{jobs.unconfirmedPages ? ' · Страницы: ' + jobs.unconfirmedPages : ''}</p><button type="button" className="secondary-button full" disabled={busy || jobs.creating || jobs.cancelling} onClick={() => void jobs.repeatUnconfirmed()}>Повторить неподтверждённую отправку</button></div>}
    {jobs.refs.length > 1 && <div className="saved-job-links" aria-label="Сохранённые задания">{jobs.refs.map(item => <button type="button" key={item.jobId} disabled={jobs.resultLoading || jobs.creating || jobs.cancelling} aria-pressed={jobs.selected?.jobId === item.jobId} onClick={() => jobs.select(item.jobId)}>{actionLabel(item.action)} · {new Date(item.createdAt * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</button>)}</div>}
    {jobs.referenceNotice && <p className="transfer-wait">{jobs.referenceNotice}</p>}
    <small>До 12 ссылок. Через час с принятия они перестают восстанавливаться и удаляются при работе приложения или следующем открытии. Сохраняются только подтверждённые номера заданий. Очистка ссылок не удаляет данные сервера.</small>
  </section>;
}
