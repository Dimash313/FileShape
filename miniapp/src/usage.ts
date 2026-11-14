/** Server-owned account allowance. Never infer quota, paid access, or purchases on the client. */
export type UsageSnapshot = {
  plan: 'free' | 'pro';
  day_utc: string;
  daily_limit: number;
  daily_used: number;
  daily_remaining: number;
  pack_remaining: number;
  pro_expires_at: number | null;
  enforced: boolean;
  purchases_enabled: boolean;
};

const fail = (): never => { throw new Error('Сервер вернул некорректный профиль. Данные скрыты.'); };

const integer = (value: unknown, max: number): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;

export function validateUsageSnapshot(input: unknown): UsageSnapshot {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return fail();
  const item = input as Record<string, unknown>;
  if (item.plan !== 'free' && item.plan !== 'pro') return fail();
  const day = item.day_utc;
  if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return fail();
  const parsed = new Date(day + 'T00:00:00Z');
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== day) return fail();
  const expected = item.plan === 'pro' ? 100 : 10;
  if (item.daily_limit !== expected || !integer(item.daily_used, Number.MAX_SAFE_INTEGER) ||
      !integer(item.daily_remaining, expected) ||
      item.daily_remaining !== Math.max(0, expected - item.daily_used) ||
      !integer(item.pack_remaining, 10_000) ||
      typeof item.enforced !== 'boolean' || typeof item.purchases_enabled !== 'boolean') return fail();
  const expiry = item.pro_expires_at;
  if (item.plan === 'pro'
    ? (typeof expiry !== 'number' || !Number.isFinite(expiry) || expiry <= 0 || expiry > 253402300799)
    : expiry !== null) return fail();
  return {
    plan: item.plan,
    day_utc: day,
    daily_limit: expected,
    daily_used: item.daily_used,
    daily_remaining: item.daily_remaining,
    pack_remaining: item.pack_remaining,
    pro_expires_at: expiry as number | null,
    enforced: item.enforced,
    purchases_enabled: item.purchases_enabled,
  };
}

export function nextUtcReset(dayUtc: string): string {
  // Day is a validated server UTC date, not the phone's local clock.
  const next = new Date(Date.parse(dayUtc + 'T00:00:00Z') + 86_400_000);
  return next.toLocaleDateString('ru-RU', { timeZone: 'UTC', day: '2-digit', month: '2-digit' }) + ' · 00:00 UTC';
}
