/** UI preflight only; server-side file validation remains authoritative. */
export const MAX_MINIAPP_FILE_BYTES = 20 * 1024 * 1024;
const MIN_BATCH_IMAGES = 2;
const MAX_BATCH_IMAGES = 8;

type SizeOnly = Pick<File, 'size'>;
type NamedSize = Pick<File, 'name' | 'size'>;

function validSize(bytes: number): boolean {
  return Number.isSafeInteger(bytes) && bytes > 0;
}

export function singleFileSelectionError(file: SizeOnly): string | null {
  if (!validSize(file.size)) {
    return 'Файл пуст или его размер не определён. Выбери другой файл.';
  }
  if (file.size > MAX_MINIAPP_FILE_BYTES) {
    return 'Максимальный размер файла для этого интерфейса — 20 МБ.';
  }
  return null;
}

/** Only currently supported image extensions; browser accept= is just a hint. */
export function batchImageSelectionError(files: readonly NamedSize[]): string | null {
  if (files.length < MIN_BATCH_IMAGES || files.length > MAX_BATCH_IMAGES) {
    return 'Выбери от 2 до 8 фотографий.';
  }
  if (files.some(file => !validSize(file.size))) {
    return 'Одно из изображений пустое или его размер не определён. Выбери другие файлы.';
  }
  if (files.some(file => !/\.(jpg|jpeg|png|webp)$/i.test(file.name))) {
    return 'Поддерживаются только JPG, PNG и WebP.';
  }
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_MINIAPP_FILE_BYTES) {
    return 'Общий размер выбранных фотографий превышает 20 МБ.';
  }
  return null;
}
