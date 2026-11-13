import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import {
  ArrowRight, Check, CirclePause, CirclePlay, Clock3,
  Copy, Link2, Plus, RefreshCw, ShieldCheck, Square, UsersRound,
} from 'lucide-react';
import {
  CampaignApiError, changeCampaignState, createCampaign,
  createCampaignInvite, listCampaigns,
} from './campaignsApi';
import type { Campaign, CampaignAction, CampaignMode, CampaignPage } from './campaignsApi';

const PAGE_SIZE = 20;
const stateLabels = {
  draft: 'Черновик',
  active: 'Активна',
  paused: 'На паузе',
  completed: 'Завершена',
  stopped: 'Остановлена',
};
const revocationLabels = {
  not_applicable: 'Ссылка не создавалась',
  not_due: 'Ссылка привязана',
  pending: 'Ожидается отзыв ссылки',
  revoked: 'Ссылка отозвана Telegram',
};
const dateTime = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

export function OwnerCampaigns() {
  const [authorized, setAuthorized] = useState(false);
  const [page, setPage] = useState<CampaignPage>({ items: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [chatId, setChatId] = useState('');
  const [mode, setMode] = useState<CampaignMode>('joins');
  const [hours, setHours] = useState('24');
  const [target, setTarget] = useState('100');
  const [confirmStop, setConfirmStop] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listCampaigns(0, PAGE_SIZE, controller.signal)
      .then(result => { setAuthorized(true); setPage(result); })
      .catch(() => { /* Never expose an owner panel to an unverified user. */ });
    return () => controller.abort();
  }, []);

  async function reload(append = false) {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const offset = append ? page.items.length : 0;
      const result = await listCampaigns(offset, PAGE_SIZE);
      setPage(previous => append
        ? { total: result.total, items: [
            ...previous.items, ...result.items.filter(
              next => !previous.items.some(old => old.campaign_id === next.campaign_id),
            ),
          ] }
        : result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось обновить кампании.');
    } finally {
      setLoading(false);
    }
  }

  async function submitDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating || busyId) return;
    const channel = Number(chatId.trim());
    const amount = Number(target.trim());
    const duration = Number(hours);
    if (!/^-100[0-9]{5,14}$/.test(chatId.trim()) || !Number.isSafeInteger(channel)) {
      setError('Введи числовой ID Telegram-канала, например -1001234567890.');
      return;
    }
    if (mode === 'joins' && (!Number.isSafeInteger(amount) || amount < 1 || amount > 1000000)) {
      setError('Укажи цель от 1 до 1 000 000 подтверждённых вступлений.');
      return;
    }
    if (![1, 3, 6, 12, 24, 48, 72].includes(duration)) {
      setError('Выбери допустимую продолжительность размещения.');
      return;
    }
    setCreating(true);
    setError(''); setNotice('');
    try {
      const start = Date.now() / 1000;
      await createCampaign({
        chat_id: channel,
        mode,
        starts_at: start,
        ends_at: start + duration * 3600,
        target_joins: mode === 'joins' ? amount : null,
      });
      setCreateOpen(false);
      setChatId('');
      setNotice('Черновик создан. Теперь создай отдельную ссылку для канала и запусти кампанию.');
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Создание кампании не подтверждено. Обнови список.');
    } finally {
      setCreating(false);
    }
  }

  async function createLink(campaign: Campaign) {
    if (busyId || creating) return;
    setBusyId(campaign.campaign_id);
    setError(''); setNotice('');
    try {
      await createCampaignInvite(campaign.campaign_id);
      setNotice('Telegram подтвердил создание отдельной пригласительной ссылки.');
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Telegram не подтвердил создание ссылки.');
    } finally {
      setBusyId(null);
    }
  }

  async function action(campaign: Campaign, command: CampaignAction) {
    if (busyId || creating) return;
    if (command === 'stop' && confirmStop !== campaign.campaign_id) {
      setConfirmStop(campaign.campaign_id);
      return;
    }
    setConfirmStop(null);
    setBusyId(campaign.campaign_id);
    setError(''); setNotice('');
    try {
      const state = await changeCampaignState(campaign.campaign_id, command);
      setNotice(`Telegram-кампания: ${stateLabels[state]}. Статус ссылки сверяй отдельно.`);
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Сервер не подтвердил изменение.');
    } finally {
      setBusyId(null);
    }
  }

  async function copyLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setNotice('Пригласительная ссылка скопирована.');
    } catch {
      setError('Не удалось скопировать ссылку. Выдели её вручную.');
    }
  }

  if (!authorized) return null;

  const confirmedOnPage = page.items.reduce((sum, item) => sum + item.confirmed_joins, 0);
  return <section className="campaign-panel" aria-label="Рекламные кампании FileShape">
    <div className="campaign-heading">
      <div className="campaign-heading-icon"><ShieldCheck size={21} /></div>
      <div>
        <span className="campaign-eyebrow">ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА</span>
        <h2>Управление рекламой</h2>
      </div>
    </div>
    <p className="campaign-description">
      Раздельные ссылки каналов, подтверждённые вступления и управление размещениями.
      Считаются события вступления, а не клики и не текущая аудитория.
    </p>
    <div className="campaign-metrics">
      <div><strong>{page.total}</strong><span>Кампаний всего</span></div>
      <div><strong>{confirmedOnPage}</strong><span>Вступлений на странице</span></div>
    </div>
    <div className="campaign-toolbar">
      <button type="button" className="campaign-primary" onClick={() => setCreateOpen(open => !open)}
        aria-expanded={createOpen}><Plus size={16}/>{createOpen ? 'Закрыть форму' : 'Новая кампания'}</button>
      <button type="button" className="campaign-secondary" onClick={() => void reload()}
        disabled={loading || creating || busyId !== null}><RefreshCw size={16}/>{loading ? 'Обновление…' : 'Обновить'}</button>
    </div>

    {createOpen && <form className="campaign-create" onSubmit={event => void submitDraft(event)}>
      <h3>Новое размещение</h3>
      <label>Числовой ID канала
        <input required type="text" inputMode="numeric" autoComplete="off" value={chatId}
          onChange={event => setChatId(event.target.value)} placeholder="-1001234567890" maxLength={20}/>
      </label>
      <fieldset className="campaign-mode">
        <legend>Условие завершения</legend>
        <label><input type="radio" name="campaign-mode" checked={mode === 'joins'}
          onChange={() => setMode('joins')}/> По вступлениям</label>
        <label><input type="radio" name="campaign-mode" checked={mode === 'duration'}
          onChange={() => setMode('duration')}/> По времени</label>
      </fieldset>
      {mode === 'joins' && <label>Цель — подтверждённых вступлений
        <input required type="number" min="1" max="1000000" step="1"
          value={target} onChange={event => setTarget(event.target.value)}/>
      </label>}
      <label>Максимальная длительность
        <select value={hours} onChange={event => setHours(event.target.value)}>
          {[1, 3, 6, 12, 24, 48, 72].map(value => <option key={value} value={value}>
            {value === 1 ? '1 час' : value < 24 ? `${value} часов` : `${value / 24} сут.`}
          </option>)}
        </select>
      </label>
      <p className="campaign-hint">Начало — сейчас. При достижении цели или истечении срока сервер завершит кампанию и запросит отзыв ссылки.</p>
      <button className="campaign-primary campaign-submit" type="submit" disabled={creating || busyId !== null}>
        {creating ? 'Создание…' : 'Создать черновик'} <ArrowRight size={16}/>
      </button>
    </form>}

    {error && <p className="campaign-message campaign-error" role="alert">{error}</p>}
    {notice && <p className="campaign-message" role="status">{notice}</p>}
    <div className="campaign-list-header">
      <h3>Кампании</h3><span>{page.items.length} из {page.total}</span>
    </div>
    {page.items.length === 0 ? <div className="campaign-empty">
      <Link2 size={22}/><strong>Пока нет кампаний</strong>
      <p>Добавь бота администратором канала с правом создавать пригласительные ссылки. Затем создай размещение.</p>
    </div> : <div className="campaign-list">
      {page.items.map(campaign => {
        const busy = busyId !== null || creating || loading;
        const ratio = campaign.mode === 'joins' && campaign.target_joins
          ? Math.min(100, Math.round(100 * campaign.confirmed_joins / campaign.target_joins)) : null;
        return <article className="campaign-card" key={campaign.campaign_id}>
          <div className="campaign-card-top">
            <div>
              <span className="campaign-card-channel">Канал {campaign.chat_id}</span>
              <strong>{campaign.mode === 'joins' ? 'По вступлениям' : 'По времени'}</strong>
            </div>
            <span className={`campaign-state campaign-state-${campaign.state}`}>{stateLabels[campaign.state]}</span>
          </div>
          <div className="campaign-card-metric"><UsersRound size={16}/>
            <strong>{campaign.confirmed_joins}</strong>
            <span>{campaign.target_joins ? `из ${campaign.target_joins}` : 'подтверждённых вступлений'}</span>
          </div>
          {ratio !== null && <div className="campaign-progress" role="progressbar"
            aria-label="Подтверждённые вступления к цели" aria-valuemin={0} aria-valuemax={100} aria-valuenow={ratio}>
            <div style={{ width: `${ratio}%` }}/>
          </div>}
          <div className="campaign-time"><Clock3 size={14}/>{dateTime(campaign.starts_at)} — {dateTime(campaign.ends_at)}</div>
          {campaign.invite_link && <div className="campaign-invite">
            <span>{campaign.invite_link}</span>
            <button type="button" aria-label="Скопировать пригласительную ссылку" onClick={() => void copyLink(campaign.invite_link!)}><Copy size={16}/></button>
          </div>}
          <p className="campaign-revoke">
            {campaign.invite_revocation === 'revoked' ? <Check size={15}/> : <Link2 size={15}/>}
            {revocationLabels[campaign.invite_revocation]}
            {campaign.invite_revocation === 'pending' && campaign.revoke_attempts > 0 &&
              ` · попыток: ${campaign.revoke_attempts}`}
          </p>
          <div className="campaign-actions">
            {campaign.state === 'draft' && !campaign.invite_link && <button type="button" disabled={busy}
              onClick={() => void createLink(campaign)}><Link2 size={16}/> Создать ссылку</button>}
            {campaign.state === 'draft' && campaign.invite_link && <button type="button" disabled={busy}
              onClick={() => void action(campaign, 'start')}><CirclePlay size={16}/> Запустить</button>}
            {campaign.state === 'active' && <button type="button" disabled={busy}
              onClick={() => void action(campaign, 'pause')}><CirclePause size={16}/> Пауза</button>}
            {campaign.state === 'paused' && <button type="button" disabled={busy}
              onClick={() => void action(campaign, 'resume')}><CirclePlay size={16}/> Возобновить</button>}
            {['draft','active','paused'].includes(campaign.state) && <button type="button" className="campaign-stop"
              disabled={busy} onClick={() => void action(campaign, 'stop')}><Square size={15}/>
              {confirmStop === campaign.campaign_id ? 'Подтвердить остановку' : 'Остановить'}
            </button>}
            {confirmStop === campaign.campaign_id && <button type="button" disabled={busy}
              onClick={() => setConfirmStop(null)}>Отмена</button>}
          </div>
        </article>;
      })}
    </div>}
    {page.items.length < page.total && <button type="button" className="campaign-more"
      disabled={loading || busyId !== null || page.items.length >= 10000}
      onClick={() => void reload(true)}>
      {loading ? 'Загрузка…' : 'Показать ещё'} <ArrowRight size={15}/>
    </button>}
    <p className="campaign-footnote">Статистика обновляется вручную. После завершения размещения ссылка может оставаться рабочей, пока Telegram не подтвердит её отзыв.</p>
  </section>;
}
