/** One bounded, cancellable status observer. Network errors never invent job states. */
export type JobState = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type JobStatus = { job_id: string; state: JobState; created_at: number; updated_at: number };

export const isTerminal = (state: JobState): boolean =>
  state === 'completed' || state === 'failed' || state === 'cancelled';

export type PollClock = {
  now(): number;
  setTimeout(callback: () => void, delay: number): unknown;
  clearTimeout(handle: unknown): void;
};
export type PollingOptions = {
  jobId: string;
  request(signal: AbortSignal): Promise<JobStatus>;
  onStatus(status: JobStatus): void;
  onNotice(message: string): void;
  available(): boolean;
  onStop?(reason: 'terminal' | 'terminal-error' | 'limit'): void;
  clock?: PollClock;
  interval?: number;
  budgetMs?: number;
  maxAttempts?: number;
};

const browserClock: PollClock = {
  now: () => globalThis.performance.now(),
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: handle => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};
const PAUSED = 'Проверка приостановлена, пока приложение скрыто или нет сети.';
const LIMITED = 'Автопроверка завершена. Нажми «Проверить статус», чтобы продолжить.';

export function startJobPolling(options: PollingOptions) {
  const clock = options.clock ?? browserClock;
  const interval = options.interval ?? 10_000;
  const budget = options.budgetMs ?? 30 * 60_000;
  const maxAttempts = options.maxAttempts ?? 180;
  if (!Number.isFinite(interval) || interval < 10_000 || interval > 60_000 ||
      !Number.isFinite(budget) || budget <= 0 || budget > 30 * 60_000 ||
      !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 180) {
    throw new RangeError('Invalid polling limits');
  }
  let disposed = false;
  let stopped = false;
  let permanentlyStopped = false;
  let attempts = 0;
  let failures = 0;
  let lastAttempt = -Infinity;
  let nextAllowed = -Infinity;
  let deadline = clock.now() + budget;
  let timer: unknown;
  let deadlineTimer: unknown;
  let current: AbortController | null = null;

  function clearTimer() {
    if (timer !== undefined) clock.clearTimeout(timer);
    timer = undefined;
  }
  function clearDeadline() {
    if (deadlineTimer !== undefined) clock.clearTimeout(deadlineTimer);
    deadlineTimer = undefined;
  }
  function limit() {
    if (disposed || stopped) return;
    stopped = true;
    clearTimer();
    clearDeadline();
    current?.abort();
    options.onNotice(LIMITED);
    options.onStop?.('limit');
  }
  function armDeadline() {
    clearDeadline();
    deadlineTimer = clock.setTimeout(limit, Math.max(0, deadline - clock.now()));
  }
  function wake() {
    clearTimer();
    if (disposed || stopped || current !== null || !options.available()) return;
    if (clock.now() >= deadline || attempts >= maxAttempts) {
      limit();
      return;
    }
    const delay = Math.max(0, nextAllowed - clock.now(), lastAttempt + interval - clock.now());
    if (delay > 0) timer = clock.setTimeout(wake, delay);
    else void poll();
  }
  async function poll() {
    if (disposed || stopped || current !== null || !options.available()) return;
    attempts += 1;
    lastAttempt = clock.now();
    nextAllowed = lastAttempt + interval;
    const controller = new AbortController();
    current = controller;
    options.onNotice('');
    try {
      const status = await options.request(controller.signal);
      if (disposed || stopped || controller.signal.aborted) return;
      if (status.job_id !== options.jobId) throw new Error('Unexpected job status');
      failures = 0;
      options.onStatus(status);
      if (isTerminal(status.state)) {
        stopped = true;
        permanentlyStopped = true;
        clearTimer();
        clearDeadline();
        options.onStop?.('terminal');
      }
    } catch (error) {
      if (disposed || stopped || controller.signal.aborted) return;
      if (typeof error === 'object' && error !== null && 'terminal' in error && error.terminal === true) {
        stopped = true;
        permanentlyStopped = true;
        clearTimer();
        clearDeadline();
        options.onNotice(error instanceof Error ? error.message : 'Задание недоступно.');
        options.onStop?.('terminal-error');
      } else {
        failures += 1;
        nextAllowed = Math.max(nextAllowed, clock.now() + Math.min(60_000, 20_000 * 2 ** Math.min(failures - 1, 2)));
        options.onNotice('Не удалось обновить статус. Повторная проверка позже.');
      }
    } finally {
      if (current === controller) current = null;
      wake();
    }
  }
  armDeadline();
  if (!options.available()) options.onNotice(PAUSED);
  wake();
  return {
    dispose() {
      disposed = true;
      clearTimer();
      clearDeadline();
      current?.abort();
    },
    availabilityChanged() {
      if (disposed || stopped) return;
      if (!options.available()) {
        clearTimer();
        current?.abort();
        options.onNotice(PAUSED);
      } else wake();
    },
    refresh() {
      if (disposed || permanentlyStopped) return;
      if (stopped) {
        stopped = false;
        attempts = 0;
        failures = 0;
        deadline = clock.now() + budget;
        armDeadline();
      }
      // Explicit refresh may shorten error backoff, never the per-request floor.
      nextAllowed = Math.max(clock.now(), lastAttempt + interval);
      wake();
    },
  };
}
