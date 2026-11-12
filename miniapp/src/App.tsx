import { useEffect, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Archive, ArrowDownToLine, ArrowRight, AudioLines, Check,
  ChevronRight, Clock3, FileImage, FileText, Files, FolderOpen,
  Image, Info, LockKeyhole, RotateCcw, ScanLine, Settings2, Sparkles,
  UploadCloud, UserRound, WandSparkles, X,
} from 'lucide-react';
import { canConvertLocally, convertLocalImage, extensionFor, type ImageFormat } from './imageTools';
import { initTelegram, tapFeedback } from './telegram';

type Tab = 'home' | 'tools' | 'history' | 'profile';
type Task = { id: number; name: string; format: string; time: string };
type Tool = { title: string; subtitle: string; icon: LucideIcon; category: string; local: boolean };
const tools: Tool[] = [
  { title: 'PDF', subtitle: 'Страницы и объединение', icon: FileText, category: 'Документы', local: false },
  { title: 'Фото', subtitle: 'JPG, PNG, WebP', icon: Image, category: 'Изображения', local: true },
  { title: 'Аудио', subtitle: 'MP3, OGG, WAV', icon: AudioLines, category: 'Медиа', local: false },
  { title: 'Архивы', subtitle: 'Создать и распаковать', icon: Archive, category: 'Архивы', local: false },
  { title: 'Сканер', subtitle: 'Скоро', icon: ScanLine, category: 'Скоро', local: false },
  { title: 'Пакетно', subtitle: 'Скоро', icon: Files, category: 'Скоро', local: false },
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
  if (name.endsWith('.pdf')) return 'pdf';
  if (/\.(mp3|ogg|oga|m4a|flac|wav)$/.test(name)) return 'audio';
  if (/\.(zip)$/.test(name)) return 'zip';
  return 'other';
}

export default function App() {
  const [tab, setTab] = useState<Tab>('home');
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<ImageFormat>('image/jpeg');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [history, setHistory] = useState<Task[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => { initTelegram(); }, []);
  const pick = () => { tapFeedback(); inputRef.current?.click(); };
  const acceptFile = (next?: File) => {
    if (!next) return;
    tapFeedback();
    if (next.size > 20 * 1024 * 1024) {
      setNotice('Максимальный размер файла для этого интерфейса — 20 МБ.');
      return;
    }
    setFile(next);
    setNotice('');
    setTab('home');
  };
  const clear = () => { setFile(null); setNotice(''); if (inputRef.current) inputRef.current.value = ''; };
  const convert = async () => {
    if (!file || !canConvertLocally(file) || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const blob = await convertLocalImage(file, format);
      const filename = `${file.name.replace(/\.[^.]+$/, '') || 'image'}_fileshape.${extensionFor(format)}`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setHistory(items => [{ id: Date.now(), name: filename, format: extensionFor(format).toUpperCase(), time: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }, ...items].slice(0, 12));
      setNotice('Готово! Файл сохранён на устройство.');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Не удалось обработать файл.');
    } finally { setBusy(false); }
  };
  const kind = file ? fileCategory(file) : 'other';
  const title = tab === 'home' ? 'Работа с файлами' : tab === 'tools' ? 'Все инструменты' : tab === 'history' ? 'История' : 'Профиль';

  return <div className="app-shell">
    <input ref={inputRef} className="visually-hidden" type="file" onChange={e => acceptFile(e.target.files?.[0])} />
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
        {!file ? <div className={`upload-area ${dragging ? 'dragging' : ''}`}
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
          </div> : <div className="pending-panel"><Info size={20}/><div><strong>Инструмент готовится к подключению</strong><p>В этой версии Mini App локально конвертирует изображения. PDF, аудио и ZIP пока обрабатываются в Telegram-боте; загрузка в сервер из приложения ещё не подключена.</p></div></div>}
          <button type="button" className="secondary-button full" onClick={pick}><RotateCcw size={16}/> Выбрать другой файл</button>
        </section>}
        <div className="section-head tools-head"><h2>Быстрые инструменты</h2><button className="text-button" onClick={() => setTab('tools')}>Все <ChevronRight size={17}/></button></div>
        <div className="tools-grid">{tools.map(tool => <button className="tool-card" type="button" key={tool.title} onClick={() => { if (tool.local) pick(); else { setTab('tools'); setNotice(`${tool.title}: серверная обработка появится после подключения API.`); } }}><tool.icon size={22} strokeWidth={1.9}/><span>{tool.title}</span></button>)}</div>
      </>}
      {tab === 'tools' && <><p className="lead">Выберите инструмент. Локальная конвертация изображений уже работает.</p><div className="tool-list">{tools.map(tool => <button type="button" className="tool-list-item" key={tool.title} onClick={() => { if (tool.local) { setTab('home'); pick(); } else setNotice(`${tool.title}: доступно в боте; подключение к Mini App — следующий этап.`); }}><div className="tool-list-icon"><tool.icon size={22}/></div><div><strong>{tool.title}</strong><span>{tool.subtitle}</span></div><ChevronRight size={19}/></button>)}</div></>}
      {tab === 'history' && <><p className="lead">Результаты текущей сессии. Файлы не сохраняются на сервере.</p>{history.length ? <div className="history-list">{history.map(item => <div className="history-item" key={item.id}><div className="tool-list-icon"><FileImage size={20}/></div><div><strong>{item.name}</strong><span>{item.format} · {item.time}</span></div><Check size={18}/></div>)}</div> : <div className="empty-state"><Clock3 size={30}/><strong>Пока пусто</strong><span>После локальной конвертации результат появится здесь.</span></div>}</>}
      {tab === 'profile' && <><p className="lead">Управление вашим рабочим пространством.</p><div className="profile-card"><div className="profile-avatar"><UserRound size={24}/></div><div><strong>FileShape Studio</strong><span>Предварительная версия 0.7</span></div></div><div className="pending-panel"><LockKeyhole size={21}/><div><strong>Приватность прежде всего</strong><p>Изображения в локальном конвертере обрабатываются прямо на устройстве. История хранится только до закрытия приложения. Аккаунты и подписки пока не подключены.</p></div></div></>}
      {notice && <div className="notice" role="status">{notice}<button aria-label="Закрыть" onClick={() => setNotice('')}><X size={16}/></button></div>}
    </main>
    <footer className="bottom-nav">{nav.map(item => <button type="button" key={item.tab} className={`nav-item ${tab === item.tab ? 'active' : ''}`} onClick={() => { tapFeedback(); setTab(item.tab); setNotice(''); }}><item.icon size={21} strokeWidth={tab === item.tab ? 2.3 : 1.8}/><span>{item.label}</span></button>)}</footer>
  </div>;
}
