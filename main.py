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
from services.file_tools import (
    MAX_MERGE_FILES,
    compress_image,
    convert_image,
    extract_pdf_pages,
    merge_pdfs,
    pdf_page_count,
    rotate_pdf,
)

router = Router()
logger = logging.getLogger(__name__)
MAX_BYTES = 20 * 1024 * 1024  # Standard Bot API download limit.
MAX_MERGE_BYTES = 60 * 1024 * 1024
MAX_OUTPUT_BYTES = 45 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
processing_slots = asyncio.Semaphore(3)


class ExtractState(StatesGroup):
    waiting_for_pages = State()


class MergeState(StatesGroup):
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
        return buttons([
            [("📄 Страницы", "pdf:info"), ("✂️ Первая страница", "pdf:first")],
            [("🔢 Выбрать страницы", "pdf:extract"), ("↻ Повернуть 90°", "pdf:rotate")],
            [("🔗 Объединить с другими PDF", "pdf:merge")],
        ])
    return buttons([
        [("→ JPG", "img:JPEG"), ("→ PNG", "img:PNG"), ("→ WebP", "img:WEBP")],
        [("🗜 Оптимизировать WebP", "img:compress")],
    ])


def attachment(message: Message):
    """Return Telegram file, extension, category, byte count (or None)."""
    if message.document:
        document = message.document
        suffix = Path(document.file_name or "").suffix.lower()
        if suffix == ".pdf":
            category = "pdf"
        elif suffix in IMAGE_EXTENSIONS:
            category = "image"
        else:
            category = None
        return document, suffix, category, document.file_size
    if message.photo:
        photo = message.photo[-1]
        return photo, ".jpg", "image", photo.file_size
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
        "Пришли PDF или изображение — я покажу доступные действия.\n"
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


@router.message(F.document | F.photo)
async def received_file(message: Message):
    if message.chat.type != "private":
        await message.answer("Для обработки файлов открой личный чат с ботом.")
        return
    file, suffix, category, size = attachment(message)
    if not category:
        await message.answer("Пока поддерживаются PDF, JPG, PNG и WebP.")
        return
    if not size_allowed(size):
        await message.answer("Файл слишком большой или размер неизвестен. Лимит: 20 МБ.")
        return
    label = "📄 PDF" if category == "pdf" else "🖼 Изображение"
    await message.answer(
        f"{label} получен. Что сделать с файлом?",
        reply_markup=file_menu(category),
        reply_to_message_id=message.message_id,
    )


@router.callback_query(F.data.startswith("pdf:") | F.data.startswith("img:"))
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
        "pdf:info", "pdf:first", "pdf:extract", "pdf:rotate", "pdf:merge"
    }
    valid_image = category == "image" and action in {
        "img:JPEG", "img:PNG", "img:WEBP", "img:compress"
    }
    if not file or not size_allowed(size) or not (valid_pdf or valid_image):
        await callback.answer("Недопустимое действие.", show_alert=True)
        return
    if await state.get_state():
        await callback.answer("Закончи текущую операцию или отправь /cancel.", show_alert=True)
        return
    await callback.answer()
    if action == "pdf:extract":
        await state.set_state(ExtractState.waiting_for_pages)
        await state.update_data(file_id=file.file_id)
        await callback.message.answer(
            "🔢 Какие страницы извлечь?\n"
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
                    else:
                        fmt = action.split(":", 1)[1]
                        ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[fmt]
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
