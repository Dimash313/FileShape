type TelegramWebApp = {
  initData?: string;
  ready(): void;
  expand(): void;
  colorScheme?: 'dark' | 'light';
  close(): void;
  HapticFeedback?: { impactOccurred(style: 'light' | 'medium' | 'heavy'): void };
};

declare global {
  interface Window { Telegram?: { WebApp?: TelegramWebApp } }
}

export function initTelegram() {
  const app = window.Telegram?.WebApp;
  if (!app) return;
  app.ready();
  app.expand();
  document.documentElement.dataset.telegramTheme = app.colorScheme ?? 'dark';
}

export function tapFeedback() {
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light');
}

export function telegramInitData(): string {
  return window.Telegram?.WebApp?.initData ?? '';
}
