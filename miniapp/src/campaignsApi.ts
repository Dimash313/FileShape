import { telegramInitData } from './telegram.js';

export type CampaignState = 'draft' | 'active' | 'paused' | 'completed' | 'stopped';
export type CampaignMode = 'duration' | 'joins';
export type CampaignAction = 'start' | 'pause' | 'resume' | 'stop';
export type InviteRevocation = 'not_applicable' | 'not_due' | 'pending' | 'revoked';

export type Campaign = {
  campaign_id: string;
  chat_id: number;
  mode: CampaignMode;
  target_joins: number | null;
  starts_at: number;
  ends_at: number;
  state: CampaignState;
  confirmed_joins: number;
  invite_link: string | null;
  invite_revocation: InviteRevocation;
  revoke_attempts: number;
  revoked_at: number | null;
  created_at?: number;
};
export type CampaignPage = { items: Campaign[]; total: number };

const PREFIX = '/api/v1/owner/campaigns';
const ID = /^[A-Za-z0-9_-]{16,64}$/;
const INVITE = /^https:\/\/t\.me\/\+[A-Za-z0-9_-]{8,128}$/;
const states: CampaignState[] = ['draft', 'active', 'paused', 'completed', 'stopped'];
const modes: CampaignMode[] = ['duration', 'joins'];
const revocations: InviteRevocation[] = ['not_applicable', 'not_due', 'pending', 'revoked'];

export class CampaignApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Некорректные данные рекламной кампании.');
  }
  return value as Record<string, unknown>;
}

export function validateCampaign(input: unknown): Campaign {
  const data = record(input);
  if (typeof data.campaign_id !== 'string' || !ID.test(data.campaign_id) ||
      !Number.isSafeInteger(data.chat_id) || (data.chat_id as number) >= 0 ||
      !modes.includes(data.mode as CampaignMode) ||
      !states.includes(data.state as CampaignState) ||
      !revocations.includes(data.invite_revocation as InviteRevocation) ||
      !Number.isFinite(data.starts_at) || (data.starts_at as number) <= 0 ||
      !Number.isFinite(data.ends_at) || (data.ends_at as number) <= (data.starts_at as number) ||
      !Number.isSafeInteger(data.confirmed_joins) || (data.confirmed_joins as number) < 0 ||
      !Number.isSafeInteger(data.revoke_attempts) || (data.revoke_attempts as number) < 0 ||
      (data.invite_link !== null && (typeof data.invite_link !== 'string' || !INVITE.test(data.invite_link))) ||
      (data.revoked_at !== null && (!Number.isFinite(data.revoked_at) || (data.revoked_at as number) <= 0)) ||
      (data.mode === 'joins' && (!Number.isSafeInteger(data.target_joins) || (data.target_joins as number) < 1)) ||
      (data.mode === 'duration' && data.target_joins !== null)) {
    throw new Error('Некорректные данные рекламной кампании.');
  }
  return data as unknown as Campaign;
}

export function validateCampaignPage(input: unknown, limit: number): CampaignPage {
  const data = record(input);
  if (!Array.isArray(data.items) || data.items.length > limit ||
      !Number.isSafeInteger(data.total) || (data.total as number) < data.items.length) {
    throw new Error('Некорректный список рекламных кампаний.');
  }
  return { items: data.items.map(validateCampaign), total: data.total as number };
}

function campaignId(id: string): string {
  if (!ID.test(id)) throw new Error('Некорректный номер кампании.');
  return id;
}

async function campaignRequest(path: string, method = 'GET', body?: object, signal?: AbortSignal): Promise<unknown> {
  const signed = telegramInitData();
  if (!signed) throw new CampaignApiError(401, 'Открой управление рекламой внутри Telegram.');
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, 18000);
  try {
    const response = await fetch(PREFIX + path, {
      method,
      headers: { 'X-Telegram-Init-Data': signed, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
      redirect: 'error',
    });
    if (!response.ok) {
      const message = response.status === 403 ? 'Доступно только владельцу FileShape.' :
        response.status === 401 ? 'Сессия Telegram устарела. Открой Mini App заново.' :
        response.status === 409 ? 'Состояние кампании изменилось. Обнови список.' :
        response.status === 422 ? 'Проверь данные кампании и сроки размещения.' :
        response.status === 503 ? 'Сервер рекламных кампаний недоступен.' :
        response.status === 502 ? 'Telegram не смог выполнить действие. Попробуй позже.' :
        'Не удалось выполнить действие. Обнови список.';
      throw new CampaignApiError(response.status, message);
    }
    return await response.json() as unknown;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}

export async function listCampaigns(offset = 0, limit = 20, signal?: AbortSignal): Promise<CampaignPage> {
  if (!Number.isInteger(offset) || offset < 0 || offset > 10000 ||
      !Number.isInteger(limit) || limit < 1 || limit > 30) throw new Error('Некорректная страница кампаний.');
  const value = await campaignRequest(`?offset=${offset}&limit=${limit}`, 'GET', undefined, signal);
  return validateCampaignPage(value, limit);
}

export type CampaignDraft = {
  chat_id: number; mode: CampaignMode; starts_at: number; ends_at: number;
  target_joins: number | null;
};

export async function createCampaign(data: CampaignDraft): Promise<string> {
  if (!Number.isSafeInteger(data.chat_id) || data.chat_id >= 0 ||
      !modes.includes(data.mode) || !Number.isFinite(data.starts_at) ||
      !Number.isFinite(data.ends_at) || data.ends_at <= data.starts_at ||
      (data.mode === 'joins' && (!Number.isSafeInteger(data.target_joins) || (data.target_joins ?? 0) < 1)) ||
      (data.mode === 'duration' && data.target_joins !== null)) {
    throw new Error('Проверь канал, сроки и цель рекламной кампании.');
  }
  const result = record(await campaignRequest('/drafts', 'POST', data));
  if (result.state !== 'draft' || typeof result.campaign_id !== 'string' || !ID.test(result.campaign_id)) {
    throw new Error('Сервер не подтвердил создание кампании. Обнови список.');
  }
  return result.campaign_id;
}

export async function createCampaignInvite(id: string): Promise<string> {
  const result = record(await campaignRequest('/' + campaignId(id) + '/invite', 'POST'));
  if (result.campaign_id !== id || typeof result.invite_link !== 'string' || !INVITE.test(result.invite_link)) {
    throw new Error('Telegram-ссылка не подтверждена сервером. Обнови список.');
  }
  return result.invite_link;
}

export async function changeCampaignState(id: string, action: CampaignAction): Promise<CampaignState> {
  if (!(['start', 'pause', 'resume', 'stop'] as string[]).includes(action)) throw new Error('Неизвестная команда.');
  const result = record(await campaignRequest('/' + campaignId(id) + '/state', 'POST', { action }));
  if (result.campaign_id !== id || !states.includes(result.state as CampaignState)) {
    throw new Error('Сервер не подтвердил изменение кампании. Обнови список.');
  }
  return result.state as CampaignState;
}

export type CampaignAnalytics = {
  campaigns_total: number;
  campaigns_by_state: Record<CampaignState, number>;
  confirmed_joins_total: number;
  confirmed_joins_last_24h: number;
  pending_revocations: number;
  revoked_links: number;
  as_of: number;
};

export function validateCampaignAnalytics(input: unknown): CampaignAnalytics {
  const data = record(input);
  const counts = record(data.campaigns_by_state);
  const nonNegative = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
  const fields = [
    data.campaigns_total, data.confirmed_joins_total,
    data.confirmed_joins_last_24h, data.pending_revocations, data.revoked_links,
  ];
  if (fields.some(value => !nonNegative(value)) ||
      states.some(state => !nonNegative(counts[state])) ||
      states.reduce((sum, state) => sum + (counts[state] as number), 0) !== data.campaigns_total ||
      typeof data.as_of !== 'number' || !Number.isFinite(data.as_of) || data.as_of <= 0 ||
      (data.confirmed_joins_last_24h as number) > (data.confirmed_joins_total as number)) {
    throw new Error('Некорректная рекламная аналитика.');
  }
  return data as unknown as CampaignAnalytics;
}

export async function getCampaignAnalytics(signal?: AbortSignal): Promise<CampaignAnalytics> {
  return validateCampaignAnalytics(await campaignRequest('/analytics', 'GET', undefined, signal));
}
