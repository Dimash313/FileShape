/**
 * Mini App tools backed by existing browser or API operations.
 * `accept` is only a native file chooser hint, never a security check:
 * server-side format and size validation remains authoritative.
 */
export const activeTools = [
  { key: 'pdf', title: 'PDF', subtitle: 'Страницы и поворот', accept: '.pdf,application/pdf' },
  { key: 'image', title: 'Фото', subtitle: 'JPG, PNG, WebP', accept: '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp' },
  { key: 'audio', title: 'Аудио', subtitle: 'MP3, OGG, WAV и другие', accept: '.mp3,.ogg,.oga,.wav,.m4a,.flac,audio/mpeg,audio/ogg,audio/wav,audio/mp4,audio/flac' },
  { key: 'documents', title: 'Документы', subtitle: 'DOCX и TXT', accept: '.docx,.txt' },
  { key: 'archive', title: 'Архивы', subtitle: 'Просмотреть ZIP', accept: '.zip,application/zip' },
  { key: 'batch', title: 'Пакетно', subtitle: '2–8 фото в один PDF', accept: null },
] as const;

export type ToolKey = (typeof activeTools)[number]['key'];
export type SingleFileToolKey = Exclude<ToolKey, 'batch'>;

/** Empty accept resets the generic home file picker to allow all files. */
export function acceptForTool(key?: SingleFileToolKey): string {
  return key ? activeTools.find(tool => tool.key === key)?.accept ?? '' : '';
}
