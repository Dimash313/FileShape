export type ImageFormat = 'image/jpeg' | 'image/png' | 'image/webp';

const IMAGE_TYPES: readonly string[] = ['image/jpeg', 'image/png', 'image/webp'];
export const MAX_LOCAL_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_PIXELS = 24_000_000;

export function canConvertLocally(file: File) {
  return IMAGE_TYPES.includes(file.type) && file.size > 0 && file.size <= MAX_LOCAL_IMAGE_BYTES;
}

export function extensionFor(type: ImageFormat) {
  return type === 'image/jpeg' ? 'jpg' : type === 'image/png' ? 'png' : 'webp';
}

export async function convertLocalImage(file: File, type: ImageFormat): Promise<Blob> {
  if (!canConvertLocally(file)) throw new Error('Поддерживаются JPG, PNG и WebP до 20 МБ.');
  const bitmap = await createImageBitmap(file);
  try {
    if (bitmap.width * bitmap.height > MAX_PIXELS) {
      throw new Error('Слишком большое разрешение изображения.');
    }
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Не удалось открыть редактор изображения.');
    if (type === 'image/jpeg') {
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
    }
    context.drawImage(bitmap, 0, 0);
    const output = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Конвертация недоступна на устройстве.')), type, 0.86);
    });
    if (output.type !== type) throw new Error('Этот формат не поддерживается браузером.');
    return output;
  } finally {
    bitmap.close();
  }
}
