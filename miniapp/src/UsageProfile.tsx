import { useEffect, useState } from 'react';
import { Clock3, RefreshCw } from 'lucide-react';
import { getUsageSnapshot } from './api';
import type { UsageSnapshot } from './usage';
import { nextUtcReset } from './usage';

/** 4.25a: live read-only account state; never show invented balances or a pay button. */
export function UsageProfile() {
  const [snapshot, setSnapshot] = useState<UsageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError('');
    setSnapshot(null);
    getUsageSnapshot(controller.signal)
      .then(value => { if (active) setSnapshot(value); })
      .catch(reason => {
        if (active) setError(reason instanceof Error ? reason.message : 'Не удалось получить профиль.');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [reload]);

  const expiry = snapshot?.pro_expires_at
    ? new Date(snapshot.pro_expires_at * 1000).toLocaleString('ru-RU', {
        timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      }) + ' UTC'
    : null;

  return <section className="usage-profile" aria-label="Лимиты аккаунта">
    <div className="usage-heading">
      <strong>Мой тариф и операции</strong>
      <button type="button" disabled={loading} onClick={() => setReload(value => value + 1)}>
        <RefreshCw size={14} aria-hidden="true"/> {loading ? 'Проверка…' : 'Обновить'}
      </button>
    </div>
    {loading ? <p className="usage-hint" role="status">Получаем данные учёта из сервера…</p>
      : error ? <p className="usage-error" role="alert">{error} Баланс не показан.</p>
      : snapshot && !snapshot.enforced
      ? <p className="usage-error" role="status">Сервер не подтвердил применение лимитов. Тариф и остатки скрыты, чтобы не показывать неподтверждённые значения.</p>
      : snapshot ? <>
        <div className="usage-plan">
          <span>Текущий тариф</span>
          <strong>{snapshot.plan === 'pro' ? 'Pro' : 'Free'}</strong>
        </div>
        {expiry && <p className="usage-hint">Pro действует до {expiry}.</p>}
        <div className="usage-grid">
          <div><strong>{snapshot.daily_remaining} / {snapshot.daily_limit}</strong><span>Осталось на сутки</span></div>
          <div><strong>{snapshot.pack_remaining}</strong><span>Дополнительных операций</span></div>
        </div>
        <p className="usage-hint">Учтено серверных операций за сутки: {snapshot.daily_used}. Принятые, но ещё не завершённые задания временно занимают лимит. Локальная обработка фото не расходует серверный лимит.</p>
        <p className="usage-reset"><Clock3 size={14} aria-hidden="true"/> Сброс дневного лимита: {nextUtcReset(snapshot.day_utc)}</p>
        <p className="usage-hint">{snapshot.purchases_enabled
          ? 'Продажи включены на сервере. Покупки доступны только через подтверждённый процесс Telegram.'
          : 'Покупки Telegram Stars пока недоступны. История покупок появится после проверки платёжной системы.'}</p>
      </> : <p className="usage-error" role="alert">Данные учёта не получены.</p>}
  </section>;
}
