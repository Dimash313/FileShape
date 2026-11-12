"""FileShape: Telegram-based PDF and image toolbox."""
import asyncio
from contextlib import suppress
import logging
from pathlib import Path
import tempfile

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import get_settings
from services.audio_tools import AUDIO_EXTENSIONS, OUTPUT_FORMATS, convert_audio, probe_audio
from services.archive_tools import MAX_BUNDLE_FILES, inspect_zip, make_zip, unpack_zip
from services.document_tools import docx_to_txt, read_docx_text, txt_info, txt_to_docx
from services.file_tools import (
    MAX_MERGE_FILES,
    compress_image,
    convert_image,
    extract_pdf_pages,
    merge_pdfs,
    pdf_page_count,
    remove_pdf_pages,
    rotate_pdf,
)

router = Router()
logger = logging.getLogger(__name__)
MAX_BYTES = 20 * 1024 * 1024  # Standard Bot API download limit.
MAX_MERGE_BYTES = 60 * 1024 * 1024
MAX_ZIP_BUNDLE_BYTES = 60 * 1024 * 1024
MAX_OUTPUT_BYTES = 45 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
processing_slots = asyncio.Semaphore(3)


class ExtractState(StatesGroup):
    waiting_for_pages = State()


class MergeState(StatesGroup):
    collecting = State()


class ZipState(StatesGroup):
    collecting = State()


def buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=code) for label, code in row]
            for row in rows
        ]
    )


def file_menu(kind: str) -> InlineKeyboardMarkup:
    if kind == "pdf":
        rows = [
            [("📄 Страницы", "pdf:info"), ("✂️ Первая", "pdf:first")],
            [("🔢 Выбрать страницы", "pdf:extract"), ("↻ Повернуть 90°", "pdf:rotate")],
            [("🔗 Объединить PDF", "pdf:merge")],
            [("🗑 Удалить страницы", "pdf:remove")],
        ]
    elif kind == "image":
        rows = [
            [("→ JPG", "img:JPEG"), ("→ PNG", "img:PNG"), ("→ WebP", "img:WEBP")],
            [("📄 → PDF", "img:PDF"), ("🗜 WebP", "img:compress")],
        ]
    elif kind == "audio":
        rows = [
            [("→ MP3", "audio:mp3"), ("→ OGG", "audio:ogg"), ("→ WAV", "audio:wav")],
            [("ℹ️ Об аудио", "audio:info")],
        ]
    elif kind == "docx":
        rows = [[("📝 → TXT", "docx:txt"), ("ℹ️ О документе", "docx:info")]]
    elif kind == "txt":
        rows = [[("📝 → DOCX", "txt:docx"), ("ℹ️ О тексте", "txt:info")]]
    elif kind == "archive":
        rows = [[("📋 Содержимое ZIP", "zip:list"), ("📂 Распаковать", "zip:extract")]]
    else:
        rows = []
    rows.append([("📦 Собрать ZIP с другими файлами", "zip:create")])
    return buttons(rows)

def attachment(message: Message):
    """Return Telegram file, extension, category, byte count (or None)."""
    if message.document:
        document = message.document
        suffix = Path(document.file_name or "").suffix.lower()
        if suffix == ".pdf":
            category = "pdf"
        elif suffix in IMAGE_EXTENSIONS:
            category = "image"
        elif suffix in AUDIO_EXTENSIONS:
            category = "audio"
        elif suffix == ".docx":
            category = "docx"
        elif suffix == ".txt":
            category = "txt"
        elif suffix == ".zip":
            category = "archive"
        else:
            category = "other"
        return document, suffix, category, document.file_size
    if message.photo:
        photo = message.photo[-1]
        return photo, ".jpg", "image", photo.file_size
    if message.voice:
        voice = message.voice
        return voice, ".ogg", "audio", voice.file_size
    if message.audio:
        audio = message.audio
        suffix = Path(audio.file_name or "").suffix.lower()
        mime_to_ext = {
            "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
            "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
            "audio/wav": ".wav", "audio/x-wav": ".wav",
            "audio/flac": ".flac", "audio/x-flac": ".flac",
        }
        if suffix not in AUDIO_EXTENSIONS:
            suffix = mime_to_ext.get(audio.mime_type or "", "")
        category = "audio" if suffix in AUDIO_EXTENSIONS else "other"
        return audio, suffix or ".bin", category, audio.file_size
    return None, "", None, None


def size_allowed(size: int | None) -> bool:
    return size is not None and 0 < size <= MAX_BYTES


def check_download(path: Path) -> None:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("File is too large")


async def send_result(message: Message, path: Path, caption: str = "✅ Готово · FileShape"):
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("Result is too large to send")
    await message.answer_document(FSInputFile(path), caption=caption)


async def remove_status(message: Message) -> None:
    with suppress(Exception):
        await message.delete()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📁 FileShape | Инструменты для файлов\n\n"
        "Пришли PDF, DOCX, TXT, ZIP, фото или аудио.\n"
        "Другие файлы можно собрать в ZIP.\n"
        "Файлы до 20 МБ. Для выхода из операции: /cancel."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✖️ Операция отменена. Отправь новый файл.")


async def run_merge(message: Message, bot: Bot, state: FSMContext):
    if await state.get_state() != MergeState.collecting.state:
        await message.answer("Сначала выбери «Объединить» для PDF.")
        return
    data = await state.get_data()
    items = data.get("pdfs", [])
    if len(items) < 2:
        await message.answer("Добавь ещё хотя бы один PDF, затем нажми «Готово».")
        return
    await state.clear()
    status = await message.answer("⏳ Объединяю PDF…")
    try:
        async with processing_slots:
            with tempfile.TemporaryDirectory(prefix="fileshape_") as directory:
                folder = Path(directory)
                paths = []
                for index, item in enumerate(items):
                    path = folder / f"part_{index}.pdf"
                    await bot.download(item["file_id"], destination=path)
                    check_download(path)
                    paths.append(path)
                target = folder / "merged.pdf"
                pages = await asyncio.to_thread(merge_pdfs, paths, target)
                await send_result(message, target, f"✅ {len(paths)} PDF · {pages} стр. | FileShape")
    except ValueError as error:
        await message.answer(f"Не удалось объединить: {error}. Начни заново.")
    except Exception:
        logger.exception("PDF merge failed")
        await message.answer("Не удалось объединить PDF. Проверь, что файлы не повреждены." )
    finally:
        await remove_status(status)


@router.message(MergeState.collecting, Command("done"))
async def done_command(message: Message, bot: Bot, state: FSMContext):
    await run_merge(message, bot, state)


@router.callback_query(F.data == "merge:done")
async def done_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    if isinstance(callback.message, Message):
        await run_merge(callback.message, bot, state)


@router.callback_query(F.data == "merge:cancel")
async def cancel_merge_button(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != MergeState.collecting.state:
        await callback.answer("Эта операция уже завершена.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Отменено")
    if isinstance(callback.message, Message):
        await callback.message.answer("✖️ Объединение отменено.")


@router.message(MergeState.collecting, F.document)
async def collect_pdf(message: Message, state: FSMContext):
    file, suffix, category, size = attachment(message)
    if category != "pdf" or not file or not size_allowed(size):
        await message.answer("Пришли PDF документом до 20 МБ.")
        return
    data = await state.get_data()
    items = data.get("pdfs", [])
    if len(items) >= MAX_MERGE_FILES:
        await message.answer("Можно объединить максимум 5 PDF. Нажми «Готово».")
        return
    if sum(item["size"] for item in items) + size > MAX_MERGE_BYTES:
        await message.answer("Суммарный лимит — 60 МБ. Выбери файл поменьше.")
        return
    items.append({"file_id": file.file_id, "size": size})
    await state.update_data(pdfs=items)
    await message.answer(
        f"✅ Добавлен PDF {len(items)}/{MAX_MERGE_FILES}. "
        "Отправь следующий или нажми «Готово».",
        reply_markup=buttons([
            [("✅ Готово", "merge:done"), ("✖️ Отмена", "merge:cancel")],
        ]),
    )


@router.message(MergeState.collecting)
async def merge_hint(message: Message):
    await message.answer("Пришли следующий PDF документом, либо /done или /cancel.")


async def run_zip_bundle(message: Message, bot: Bot, state: FSMContext):
    if await state.get_state() != ZipState.collecting.state:
        await message.answer("Сначала выбери «Собрать ZIP» у файла.")
        return
    data = await state.get_data()
    items = data.get("zip_files", [])
    if len(items) < 2:
        await message.answer("Добавь ещё один файл, затем нажми «Готово».")
        return
    await state.clear()
    status = await message.answer("⏳ Создаю ZIP…")
    try:
        async with processing_slots:
            with tempfile.TemporaryDirectory(prefix="fileshape_") as directory:
                folder = Path(directory)
                inputs = []
                for index, item in enumerate(items):
                    path = folder / f"item_{index}"
                    await bot.download(item["file_id"], destination=path)
                    check_download(path)
                    inputs.append((path, item["name"]))
                target = folder / "fileshape.zip"
                await asyncio.to_thread(make_zip, inputs, target)
                await send_result(message, target, f"✅ ZIP из {len(items)} файлов · FileShape")
    except ValueError as error:
        await message.answer(f"Не удалось собрать ZIP: {error}.")
    except Exception:
        logger.exception("ZIP creation failed")
        await message.answer("Не удалось собрать ZIP. Попробуй файлы поменьше.")
    finally:
        await remove_status(status)


@router.message(ZipState.collecting, Command("done"))
async def done_zip_command(message: Message, bot: Bot, state: FSMContext):
    await run_zip_bundle(message, bot, state)


@router.callback_query(F.data == "bundle:done")
async def done_zip_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    if isinstance(callback.message, Message):
        await run_zip_bundle(callback.message, bot, state)


@router.callback_query(F.data == "bundle:cancel")
async def cancel_zip_button(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != ZipState.collecting.state:
        await callback.answer("Эта операция уже завершена.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Отменено")
    if isinstance(callback.message, Message):
        await callback.message.answer("✖️ Создание ZIP отменено.")


@router.message(ZipState.collecting, F.document | F.photo)
async def collect_zip_file(message: Message, state: FSMContext):
    file, suffix, category, size = attachment(message)
    if not file or not size_allowed(size):
        await message.answer("Пришли файл до 20 МБ.")
        return
    data = await state.get_data()
    items = data.get("zip_files", [])
    if len(items) >= MAX_BUNDLE_FILES:
        await message.answer("Максимум 5 файлов. Нажми «Готово».")
        return
    if sum(item["size"] for item in items) + size > MAX_ZIP_BUNDLE_BYTES:
        await message.answer("Суммарный лимит — 60 МБ. Выбери файл поменьше.")
        return
    items.append({
        "file_id": file.file_id,
        "size": size,
        "name": getattr(file, "file_name", None) or f"photo_{len(items)+1}.jpg",
    })
    await state.update_data(zip_files=items)
    await message.answer(
        f"✅ Добавлено файлов: {len(items)}/{MAX_BUNDLE_FILES}.",
        reply_markup=buttons([[("✅ Готово", "bundle:done"), ("✖️ Отмена", "bundle:cancel")]]),
    )


@router.message(ZipState.collecting)
async def zip_hint(message: Message):
    await message.answer("Пришли следующий файл или нажми «Готово». Отмена: /cancel.")


@router.message(ExtractState.waiting_for_pages)
async def extract_by_range(message: Message, bot: Bot, state: FSMContext):
    spec = (message.text or "").strip()
    if not spec or len(spec) > 90:
        await message.answer("Укажи страницы, например: 1,3-5. Или /cancel.")
        return
    data = await state.get_data()
    file_id = data.get("file_id")
    if not file_id:
        await state.clear()
        await message.answer("Файл не найден. Пришли PDF заново.")
        return
    status = await message.answer("⏳ Извлекаю страницы…")
    try:
        async with processing_slots:
            with tempfile.TemporaryDirectory(prefix="fileshape_") as directory:
                folder = Path(directory)
                source = folder / "source.pdf"
                await bot.download(file_id, destination=source)
                check_download(source)
                target = folder / "pages.pdf"
                if data.get("pdf_mode") == "pdf:remove":
                    target = folder / "without_pages.pdf"
                    count = await asyncio.to_thread(remove_pdf_pages, source, target, spec)
                    await send_result(message, target, f"✅ Осталось страниц: {count} | FileShape")
                else:
                    count = await asyncio.to_thread(extract_pdf_pages, source, target, spec)
                    await send_result(message, target, f"✅ Извлечено страниц: {count} | FileShape")
        await state.clear()
    except ValueError as error:
        await message.answer(f"Не удалось выбрать страницы: {error}. Попробуй ещё раз или /cancel.")
    except Exception:
        logger.exception("PDF extraction failed")
        await state.clear()
        await message.answer("Не удалось обработать PDF. Пришли файл заново.")
    finally:
        await remove_status(status)


@router.message(F.document | F.photo | F.audio | F.voice)
async def received_file(message: Message):
    if message.chat.type != "private":
        await message.answer("Для обработки файлов открой личный чат с ботом.")
        return
    file, suffix, category, size = attachment(message)
    if not category:
        await message.answer("Пришли документ или изображение.")
        return
    if not size_allowed(size):
        await message.answer("Файл слишком большой или размер неизвестен. Лимит: 20 МБ.")
        return
    label = {
        "pdf": "📄 PDF", "image": "🖼 Изображение",
        "docx": "📝 DOCX", "txt": "📝 TXT",
        "archive": "📦 ZIP", "audio": "🎧 Аудио", "other": "📎 Файл",
    }[category]
    await message.answer(
        f"{label} · {size / 1024 / 1024:.1f} МБ\nВыбери действие ↓",
        reply_markup=file_menu(category),
        reply_to_message_id=message.message_id,
    )


@router.callback_query(F.data.startswith(("pdf:", "img:", "docx:", "txt:", "zip:", "audio:")))
async def run_action(callback: CallbackQuery, bot: Bot, state: FSMContext):
    action = callback.data or ""
    if not isinstance(callback.message, Message):
        await callback.answer("Отправь файл заново.", show_alert=True)
        return
    origin = callback.message.reply_to_message
    if (
        callback.message.chat.type != "private"
        or not origin
        or not origin.from_user
        or origin.from_user.id != callback.from_user.id
    ):
        await callback.answer("Эта кнопка не для тебя. Отправь свой файл.", show_alert=True)
        return
    file, suffix, category, size = attachment(origin)
    valid_pdf = category == "pdf" and action in {
        "pdf:info", "pdf:first", "pdf:extract", "pdf:rotate", "pdf:merge", "pdf:remove"
    }
    valid_image = category == "image" and action in {
        "img:JPEG", "img:PNG", "img:WEBP", "img:PDF", "img:compress"
    }
    valid_audio = category == "audio" and action in {
        "audio:mp3", "audio:ogg", "audio:wav", "audio:info"
    }
    valid_docx = category == "docx" and action in {"docx:info", "docx:txt"}
    valid_txt = category == "txt" and action in {"txt:info", "txt:docx"}
    valid_zip = category == "archive" and action in {"zip:list", "zip:extract"}
    valid_bundle = action == "zip:create"
    if not file or not size_allowed(size) or not (
        valid_pdf or valid_image or valid_audio or valid_docx or valid_txt or valid_zip or valid_bundle
    ):
        await callback.answer("Недопустимое действие.", show_alert=True)
        return
    if await state.get_state():
        await callback.answer("Закончи текущую операцию или отправь /cancel.", show_alert=True)
        return
    await callback.answer()
    if action == "zip:create":
        await state.set_state(ZipState.collecting)
        suggested_name = getattr(file, "file_name", None) or "photo.jpg"
        await state.update_data(zip_files=[{
            "file_id": file.file_id, "size": size, "name": suggested_name,
        }])
        await callback.message.answer(
            "📦 Создание ZIP · 1/5\n\n"
            "Отправь ещё от 1 до 4 файлов в нужном порядке.\n"
            "Затем нажми «Готово».",
            reply_markup=buttons([[("✅ Готово", "bundle:done"), ("✖️ Отмена", "bundle:cancel")]]),
        )
        return
    if action in {"pdf:extract", "pdf:remove"}:
        await state.set_state(ExtractState.waiting_for_pages)
        await state.update_data(file_id=file.file_id, pdf_mode=action)
        verb = "удалить" if action == "pdf:remove" else "извлечь"
        await callback.message.answer(
            f"🔢 Какие страницы {verb}?\n"
            "Например: 1,3-5 (первая, третья, четвёртая и пятая).\n"
            "Для отмены: /cancel"
        )
        return
    if action == "pdf:merge":
        await state.set_state(MergeState.collecting)
        await state.update_data(pdfs=[{"file_id": file.file_id, "size": size}])
        await callback.message.answer(
            "🔗 Объединение PDF · 1/5\n\n"
            "Пришли ещё от 1 до 4 PDF документами.\n"
            "Порядок отправки = порядок страниц.",
            reply_markup=buttons([
                [("✅ Готово", "merge:done"), ("✖️ Отмена", "merge:cancel")],
            ]),
        )
        return
    status = await callback.message.answer("⏳ Обрабатываю файл…")
    try:
        async with processing_slots:
            with tempfile.TemporaryDirectory(prefix="fileshape_") as directory:
                folder = Path(directory)
                source = folder / ("source" + suffix)
                await bot.download(file, destination=source)
                check_download(source)
                if action == "pdf:info":
                    count = await asyncio.to_thread(pdf_page_count, source)
                    await callback.message.answer(f"📄 В PDF страниц: {count}.")
                elif action == "audio:info":
                    info = await asyncio.to_thread(probe_audio, source)
                    await callback.message.answer(
                        f"🎧 Аудио · {info['seconds']:.1f} сек. · "
                        f"кодек {info['codec']}\n"
                        "Конвертация доступна для записей до 10 минут."
                    )
                elif action == "docx:info":
                    _text, info = await asyncio.to_thread(read_docx_text, source)
                    await callback.message.answer(
                        f"📝 DOCX: абзацев {info['paragraphs']}, таблиц {info['tables']}, "
                        f"символов {info['characters']}."
                    )
                elif action == "txt:info":
                    info = await asyncio.to_thread(txt_info, source)
                    await callback.message.answer(
                        f"📝 TXT: строк {info['lines']}, символов {info['characters']}."
                    )
                elif action == "zip:list":
                    info = await asyncio.to_thread(inspect_zip, source)
                    names = "\n".join("• " + name[:100] for name in info["names"])
                    await callback.message.answer(
                        f"📦 ZIP: файлов {info['files']}, распакованный размер "
                        f"≈ {info['bytes'] // 1024} КБ.\n"
                        f"{names or 'Архив пуст.'}"
                    )
                elif action == "zip:extract":
                    entries = await asyncio.to_thread(unpack_zip, source, folder)
                    for path, name in entries:
                        await send_result(callback.message, path, f"📂 {name}")
                else:
                    if action == "pdf:first":
                        target = folder / "first_page.pdf"
                        await asyncio.to_thread(extract_pdf_pages, source, target, "1")
                    elif action == "pdf:rotate":
                        target = folder / "rotated.pdf"
                        await asyncio.to_thread(rotate_pdf, source, target, 90)
                    elif action == "img:compress":
                        target = folder / "optimized.webp"
                        await asyncio.to_thread(compress_image, source, target)
                    elif action.startswith("audio:"):
                        fmt = action.split(":", 1)[1]
                        target = folder / ("audio" + OUTPUT_FORMATS[fmt])
                        await asyncio.to_thread(convert_audio, source, target, fmt)
                    elif action == "docx:txt":
                        target = folder / "document.txt"
                        await asyncio.to_thread(docx_to_txt, source, target)
                    elif action == "txt:docx":
                        target = folder / "document.docx"
                        await asyncio.to_thread(txt_to_docx, source, target)
                    else:
                        fmt = action.split(":", 1)[1]
                        ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "PDF": ".pdf"}[fmt]
                        target = folder / ("converted" + ext)
                        await asyncio.to_thread(convert_image, source, target, fmt)
                    await send_result(callback.message, target)
    except ValueError as error:
        await callback.message.answer(f"Не удалось обработать файл: {error}.")
    except Exception:
        logger.exception("File processing failed")
        await callback.message.answer("Не удалось обработать файл. Проверь формат и попробуй снова.")
    finally:
        await remove_status(status)


async def main():
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
