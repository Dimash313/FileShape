import { useEffect, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Archive, ArrowDownToLine, ArrowRight, AudioLines, Check,
  ChevronRight, Clock3, FileImage, FileText, Files, FolderOpen,
  Image, Info, LockKeyhole, RotateCcw, ScanLine, Settings2, Sparkles,
  UploadCloud, UserRound, WandSparkles, X,
} from 'lucide-react';
import { canConvertLocally, convertLocalImage, extensionFor, type ImageFormat } from './imageTools';
import { initTelegram, tapFeedback, telegramInitData } from './telegram';
import { actionsFor, downloadBlob, runMultiImagePdf, runServerAction } from './api';
import type { UploadProgress } from './api';

type Tab = 'home' | 'tools' | 'history' | 'profile';
type Task = { id: number; name: string; format: string; time: string; blob?: Blob };
type Tool = { title: string; subtitle: string; icon: LucideIcon; category: string; local: boolean };
const tools: Tool[] = [
  { title: 'PDF', subtitle: 'Страницы и объединение', icon: FileText, category: 'Документы', local: false },
  { title: 'Фото', subtitle: 'JPG, PNG, WebP', icon: Image, category: 'Изображения', local: true },
  { title: 'Аудио', subtitle: 'MP3, OGG, WAV', icon: AudioLines, category: 'Медиа', local: false },
  { title: 'Архивы', subtitle: 'Создать и распаковать', icon: Archive, category: 'Архивы', local: false },
  { title: 'Сканер', subtitle: 'Скоро', icon: ScanLine, category: 'Скоро', local: false },
  { title: 'Пакетно', subtitle: '2–8 фото в один PDF', icon: Files, category: 'PDF', local: false },
];
const nav: { tab: Tab; label: string; icon: LucideIcon }[] = [
  { tab: 'home', label: 'Главная', icon: FolderOpen },
  { tab: 'tools', label: 'Инструменты', icon: WandSparkles },
  { tab: 'history', label: 'История', icon: Clock3 },
  { tab: 'profile', label: 'Профиль', icon: UserRound },
];
const formats: { value: ImageFormat; label: string }[] = [
  { value: 'image/jpeg', label: 'JPG' },
  { value: 'image/png', label: 'PNG' },
  { value: 'image/webp', label: 'WebP' },
];

function sizeLabel(size: number) {
  return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} КБ` : `${(size / 1024 / 1024).toFixed(1)} МБ`;
}

function fileCategory(file: File) {
  if (canConvertLocally(file)) return 'image';
  const name = file.name.toLowerCase();
  if (/\.(jpg|jpeg|png|webp)$/.test(name)) return 'image';
  if (name.endsWith('.pdf')) return 'pdf';
  if (name.endsWith('.docx')) return 'docx';
  if (name.endsWith('.txt')) return 'txt';
  if (/\.(mp3|ogg|oga|m4a|flac|wav)$/.test(name)) return 'audio';
  if (/\.(zip)$/.test(name)) return 'zip';
  return 'other';
}

function ProgressIndicator({ progress }: { progress: UploadProgress }) {
  return <div className="transfer-status" role="status" aria-live="polite">
    <div className="transfer-label">
      <span>{progress.stage === 'upload' ? 'Загрузка файла' : 'Обработка на сервере'}</span>
      <strong>{progress.stage === 'upload' && progress.percent !== null ? progress.percent + '%' : '…'}</strong>
    </div>
    {progress.stage === 'upload' && progress.percent !== null
      ? <div className="transfer-track" role="progressbar" aria-valuenow={progress.percent} aria-valuemin={0} aria-valuemax={100}><div style={{ width: progress.percent + '%' }} /></div>
      : <div className="transfer-wait">Без выдуманных процентов — показываем реальный этап операции.</div>}
  </div>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>('home');
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<ImageFormat>('image/jpeg');
  const [serverAction, setServerAction] = useState('');
  const [pages, setPages] = useState('');
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [batchMode, setBatchMode] = useState(false);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [notice, setNotice] = useState('');
  const [history, setHistory] = useState<Task[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const batchInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => { initTelegram(); }, []);
  const pick = () => { tapFeedback(); setBatchMode(false); inputRef.current?.click(); };
  const pickBatch = () => { tapFeedback(); batchInputRef.current?.click(); };
  const showBatch = () => {
    tapFeedback(); setBatchMode(true); setBatchFiles([]); setFile(null);
    setTab('home'); setNotice(''); setProgress(null);
  };
  const chooseBatch = (files: File[]) => {
    if (!files.length) return;
    if (files.length < 2 || files.length > 8) {
      setNotice('Выбери от 2 до 8 фотографий.');
      return;
    }
    if (files.some(file => !/\.(jpg|jpeg|png|webp)$/i.test(file.name) || file.size <= 0)) {
      setNotice('Поддерживаются только JPG, PNG и WebP.');
      return;
    }
    if (files.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024) {
      setNotice('Общий размер выбранных фотографий превышает 20 МБ.');
      return;
    }
    setBatchFiles(files); setBatchMode(true); setFile(null); setNotice('');
  };
  const reorderBatch = (index: number, change: number) => {
    setBatchFiles(files => {
      const next = [...files];
      const target = index + change;
      if (target < 0 || target >= next.length) return files;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };
  const remember = (name: string, blob: Blob) => {
    const task: Task = {
      id: Date.now(), name, blob: blob.size <= 20 * 1024 * 1024 ? blob : undefined,
      format: name.split('.').pop()?.toUpperCase() ?? 'ФАЙЛ',
      time: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
    };
    setHistory(items => {
      let remaining = 35 * 1024 * 1024;
      return [task, ...items].slice(0, 12).map((item, index) => {
        if (item.blob && index < 4 && item.blob.size <= remaining) {
          remaining -= item.blob.size;
          return item;
        }
        return { ...item, blob: undefined };
      });
    });
  };
  const acceptFile = (next?: File) => {
    if (!next) return;
    tapFeedback();
    if (next.size > 20 * 1024 * 1024) {
      setNotice('Максимальный размер файла для этого интерфейса — 20 МБ.');
      return;
    }
    setFile(next);
    setBatchFiles([]);
    setBatchMode(false);
    setServerAction('');
    setPages('');
    setNotice('');
    setTab('home');
  };
  const clear = () => { setFile(null); setBatchMode(false); setBatchFiles([]); setNotice(''); setProgress(null); if (inputRef.current) inputRef.current.value = ''; };
  const convert = async () => {
    if (!file || !canConvertLocally(file) || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const blob = await convertLocalImage(file, format);
      const filename = `${file.name.replace(/\.[^.]+$/, '') || 'image'}_fileshape.${extensionFor(format)}`;
      downloadBlob(blob, filename);
      remember(filename, blob);
      setNotice('Готово! Файл сохранён на устройство.');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Не удалось обработать файл.');
    } finally { setBusy(false); }
  };
  const kind = file ? fileCategory(file) : 'other';
  const serverActions = actionsFor[kind] ?? [];
  const selectedAction = serverActions.some(option => option.code === serverAction)
    ? serverAction : (serverActions[0]?.code ?? '');
  const selectedOption = serverActions.find(option => option.code === selectedAction);
  const serverConvert = async () => {
    if (!file || busy || !selectedAction) return;
    if (selectedOption?.pages && !/^[0-9,\s-]{1,90}$/.test(pages.trim())) {
      setNotice('Введи номера страниц, например 1,3-5.');
      return;
    }
    setBusy(true);
    setNotice('');
    setProgress({ stage: 'upload', percent: null });
    try {
      const result = await runServerAction(file, selectedAction, pages.trim(), setProgress);
      if (result.type === 'info') {
        setNotice(result.text);
      } else {
        downloadBlob(result.blob, result.name);
        remember(result.name, result.blob);
        setNotice('Готово! Результат отправлен на загрузку.');
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Ошибка соединения с сервером.');
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  const convertBatch = async () => {
    if (busy || batchFiles.length < 2 || !telegramInitData()) return;
    setBusy(true); setNotice(''); setProgress({ stage: 'upload', percent: null });
    try {
      const result = await runMultiImagePdf(batchFiles, setProgress);
      if (result.type === 'file') {
        downloadBlob(result.blob, result.name);
        remember(result.name, result.blob);
        setNotice('Готово! PDF создан из ' + batchFiles.length + ' изображений.');
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Не удалось объединить изображения.');
    } finally {
      setBusy(false); setProgress(null);
    }
  };
  const title = tab === 'home' ? 'Работа с файлами' : tab === 'tools' ? 'Все инструменты' : tab === 'history' ? 'История' : 'Профиль';

  return <div className="app-shell">
    <input ref={inputRef} className="visually-hidden" type="file" onChange={e => acceptFile(e.target.files?.[0])} />
    <input ref={batchInputRef} className="visually-hidden" type="file" multiple accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
      onChange={e => chooseBatch(Array.from(e.target.files ?? []))} />
    <header className="topbar">
      <div className="brand">
        <div className="brand-icon"><Files size={22} strokeWidth={2.4} /></div>
        <div><div className="brand-name">FileShape<span className="brand-dot">.</span></div><div className="brand-caption">STUDIO</div></div>
      </div>
      <button className="icon-button" type="button" aria-label="Профиль" onClick={() => setTab('profile')}><Settings2 size={20} /></button>
    </header>
    <main>
      <div className="page-kicker">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <h1>{title}<span className="blue-dot">.</span></h1>
      {tab === 'home' && <>
        <p className="lead">Всё необходимое для ваших документов в одном месте.</p>
        {batchMode ? <section className="selected-file">
          <div className="section-head"><h2>Фото → один PDF</h2><button type="button" className="text-button" onClick={clear}>Закрыть <X size={14}/></button></div>
          <p className="batch-intro">Выбери от 2 до 8 изображений. Порядок ниже станет порядком страниц PDF.</p>
          <button type="button" className="secondary-button full" disabled={busy} onClick={pickBatch}><UploadCloud size={17}/> Выбрать фотографии</button>
          {batchFiles.length > 0 && <div className="batch-list">
            {batchFiles.map((photo, index) => <div className="batch-row" key={index}>
              <span className="batch-number">{index + 1}</span>
              <div className="batch-file"><strong title={photo.name}>{photo.name}</strong><span>{sizeLabel(photo.size)}</span></div>
              <button aria-label="Переместить выше" type="button" disabled={index === 0 || busy} onClick={() => reorderBatch(index, -1)}>↑</button>
              <button aria-label="Переместить ниже" type="button" disabled={index === batchFiles.length - 1 || busy} onClick={() => reorderBatch(index, 1)}>↓</button>
            </div>)}
          </div>}
          <div className="batch-summary">{batchFiles.length} фото · {sizeLabel(batchFiles.reduce((sum, photo) => sum + photo.size, 0))} всего</div>
          {!telegramInitData() && <div className="transfer-wait">Создание PDF работает после открытия Mini App внутри Telegram.</div>}
          <button type="button" className="primary-button full" disabled={busy || batchFiles.length < 2 || !telegramInitData()} onClick={convertBatch}>
            {busy ? 'Обрабатываю…' : 'Создать PDF'} <ArrowDownToLine size={17}/>
          </button>
        </section> : !file ? <div className={`upload-area ${dragging ? 'dragging' : ''}`}
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={e => { e.preventDefault(); setDragging(false); }}
          onDrop={e => { e.preventDefault(); setDragging(false); acceptFile(e.dataTransfer.files[0]); }}>
          <div className="upload-icon"><UploadCloud size={30} strokeWidth={1.8}/></div>
          <h2>Добавьте файл</h2>
          <p>PDF, изображение, аудио или архив</p>
          <button type="button" className="primary-button" onClick={pick}>Выбрать файл <ArrowRight size={17}/></button>
          <div className="upload-footnote"><LockKeyhole size={13}/> До 20 МБ · Безопасная обработка</div>
        </div> : <section className="selected-file">
          <div className="section-head"><h2>Выбранный файл</h2><button className="text-button" onClick={clear}>Сбросить <X size={14}/></button></div>
          <div className="file-card"><div className="file-icon"><FileText size={24}/></div><div className="file-details"><strong title={file.name}>{file.name}</strong><span>{sizeLabel(file.size)} · {file.name.split('.').pop()?.toUpperCase() ?? 'Файл'}</span></div><Check size={19} className="file-check"/></div>
          {kind === 'image' ? <div className="convert-panel">
            <div className="panel-title"><Sparkles size={17}/> Быстрая конвертация</div>
            <p>Выберите формат для сохранения изображения на устройство.</p>
            <div className="format-options">{formats.map(item => <button type="button" key={item.value} className={`format-chip ${format === item.value ? 'active' : ''}`} onClick={() => setFormat(item.value)}>{item.label}</button>)}</div>
            <button className="primary-button full" disabled={busy} onClick={convert}>{busy ? 'Обрабатываю…' : 'Конвертировать'} <ArrowDownToLine size={17}/></button>
          </div> : null}
          {serverActions.length > 0 ? <div className="convert-panel server-panel">
            <div className="panel-title"><Sparkles size={17}/> Серверные инструменты</div>
            <p>{telegramInitData() ? 'Файл обрабатывается во временной папке сервера и удаляется после отправки.' : 'Для серверной обработки открой приложение внутри Telegram.'}</p>
            <div className="server-options">
              {serverActions.map(option => <button type="button" key={option.code}
                className={selectedAction === option.code ? 'server-option active' : 'server-option'}
                onClick={() => { setServerAction(option.code); setNotice(''); }}>{option.label}</button>)}
            </div>
            {selectedOption?.pages && <label className="pages-field">Номера страниц
              <input type="text" value={pages} onChange={event => setPages(event.target.value)}
                placeholder="Например: 1,3-5" maxLength={90} />
            </label>}
            <button className="primary-button full" disabled={busy || !telegramInitData()} onClick={serverConvert}>
              {busy ? 'Обрабатываю…' : 'Выполнить'} <ArrowRight size={17}/>
            </button>
          </div> : kind !== 'image' ? <div className="pending-panel"><Info size={20}/><div><strong>Формат пока не поддерживается</strong><p>Попробуй PDF, TXT, DOCX, ZIP, изображение или аудио.</p></div></div> : null}
          <button type="button" className="secondary-button full" onClick={pick}><RotateCcw size={16}/> Выбрать другой файл</button>
        </section>}
        {progress && <ProgressIndicator progress={progress} />}
        <div className="section-head tools-head"><h2>Быстрые инструменты</h2><button className="text-button" onClick={() => setTab('tools')}>Все <ChevronRight size={17}/></button></div>
        <div className="tools-grid">{tools.map(tool => <button className="tool-card" type="button" key={tool.title} onClick={() => { if (tool.title === 'Сканер') { setTab('tools'); setNotice('Сканер появится позже.'); } else if (tool.title === 'Пакетно') showBatch(); else pick(); }}><tool.icon size={22} strokeWidth={1.9}/><span>{tool.title}</span></button>)}</div>
      </>}
      {tab === 'tools' && <><p className="lead">Изображения обрабатываются локально. Для PDF, аудио и документов доступен серверный конвертер.</p><div className="tool-list">{tools.map(tool => <button type="button" className="tool-list-item" key={tool.title} onClick={() => { if (tool.title === 'Сканер') setNotice('Сканер появится позже.'); else if (tool.title === 'Пакетно') showBatch(); else { setTab('home'); pick(); } }}><div className="tool-list-icon"><tool.icon size={22}/></div><div><strong>{tool.title}</strong><span>{tool.subtitle}</span></div><ChevronRight size={19}/></button>)}</div></>}
      {tab === 'history' && <><div className="section-head"><h2>Последние операции</h2><button type="button" className="text-button" disabled={!history.length} onClick={() => setHistory([])}>Очистить</button></div><p className="lead">Результаты текущей сессии. Последние небольшие файлы можно скачать повторно.</p>{history.length ? <div className="history-list">{history.map(item => <div className="history-item" key={item.id}><div className="tool-list-icon"><FileImage size={20}/></div><div><strong>{item.name}</strong><span>{item.format} · {item.time}</span></div>{item.blob ? <button type="button" className="history-download" onClick={() => { if (item.blob) downloadBlob(item.blob, item.name); }} aria-label={'Скачать ' + item.name}><ArrowDownToLine size={17}/></button> : <Check size={18}/>}</div>)}</div> : <div className="empty-state"><Clock3 size={30}/><strong>Пока пусто</strong><span>После конвертации результат появится здесь.</span></div>}</>}
      {tab === 'profile' && <><p className="lead">Управление вашим рабочим пространством.</p><div className="profile-card"><div className="profile-avatar"><UserRound size={24}/></div><div><strong>FileShape Studio</strong><span>Предварительная версия 1.4</span></div></div><div className="pending-panel"><LockKeyhole size={21}/><div><strong>Приватность прежде всего</strong><p>Локальные изображения обрабатываются на устройстве. Серверные файлы обрабатываются во временных папках и удаляются. Недавние небольшие результаты доступны для повторного скачивания в текущей сессии. Сервер не хранит историю.</p></div></div></>}
      {notice && <div className="notice" role="status">{notice}<button aria-label="Закрыть" onClick={() => setNotice('')}><X size={16}/></button></div>}
    </main>
    <footer className="bottom-nav">{nav.map(item => <button type="button" key={item.tab} className={`nav-item ${tab === item.tab ? 'active' : ''}`} onClick={() => { tapFeedback(); setTab(item.tab); setNotice(''); }}><item.icon size={21} strokeWidth={tab === item.tab ? 2.3 : 1.8}/><span>{item.label}</span></button>)}</footer>
  </div>;
}
