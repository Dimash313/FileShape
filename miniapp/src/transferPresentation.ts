/** Display-only transfer states, never an estimate of server conversion progress. */
export type TransferStage = 'upload' | 'validation' | 'processing';
export type TransferProgress = { stage: TransferStage; percent: number | null };
export type TransferPresentation = {
  label: string;
  detail: string;
  uploadPercent: number | null;
  uploadValueText: string | null;
};

/**
 * A percentage is truthful only while the browser reports loaded/total upload
 * bytes. No percentage is available for server validation or processing.
 */
export function describeTransfer(progress: TransferProgress): TransferPresentation {
  if (progress.stage === 'validation') {
    return {
      label: 'Ожидание подтверждения сервера',
      detail: 'Файл передан. Ожидаем подтверждения приёма задания.',
      uploadPercent: null,
      uploadValueText: null,
    };
  }
  if (progress.stage === 'processing') {
    return {
      label: 'Ожидание результата сервера',
      detail: 'Файл передан. Ожидаем ответа по операции.',
      uploadPercent: null,
      uploadValueText: null,
    };
  }
  const percent = Number.isInteger(progress.percent) && progress.percent !== null
    && progress.percent >= 0 && progress.percent <= 100 ? progress.percent : null;
  return {
    label: 'Загрузка файла',
    detail: 'Передаём файл на сервер…',
    uploadPercent: percent,
    uploadValueText: percent === null ? null : `Передано ${percent}% файла`,
  };
}
