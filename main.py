"""FileShape Telegram bot: safe MVP for PDF and image handling."""
import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import get_settings
from services.file_tools import convert_image, split_pdf

router = Router()
MAX_BYTES = 20 * 1024 * 1024
ALLOWED_IMAGE = {'.jpg', '.jpeg', '.png', '.webp'}


def menu(kind: str) -> InlineKeyboardMarkup:
    if kind == 'pdf':
        choices = [('📄 Извлечь первую страницу', 'pdf:first')]
    else:
        choices = [('JPG', 'image:JPEG'), ('PNG', 'image:PNG'), ('WebP', 'image:WEBP')]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=data) for title, data in choices]
    ])


@router.message(CommandStart())
async def start(message: Message):
    await message.answer('📁 FileShape\\n\\nОтправь PDF или изображение документом. Я предложу доступные действия.')


@router.message(F.document)
async def document(message: Message):
    doc = message.document
    suffix = Path(doc.file_name or '').suffix.lower()
    if doc.file_size is None or doc.file_size > MAX_BYTES:
        await message.answer('Файл слишком большой или размер неизвестен. Лимит: 20 МБ.')
        return
    if suffix == '.pdf':
        kind = 'pdf'
    elif suffix in ALLOWED_IMAGE:
        kind = 'image'
    else:
        await message.answer('Пока поддерживаются PDF, JPG, PNG и WebP.')
        return
    await message.answer('Выбери действие:', reply_markup=menu(kind), reply_to_message_id=message.message_id)


@router.callback_query(F.data.startswith(('pdf:', 'image:')))
async def process(callback: CallbackQuery, bot: Bot):
    action = callback.data or ''
    origin = callback.message.reply_to_message if callback.message else None
    doc = origin.document if origin else None
    if not doc or not callback.message or not origin.from_user or origin.from_user.id != callback.from_user.id:
        await callback.answer('Отправь файл заново.', show_alert=True)
        return
    suffix = Path(doc.file_name or '').suffix.lower()
    valid = (action == 'pdf:first' and suffix == '.pdf') or (action in {'image:JPEG', 'image:PNG', 'image:WEBP'} and suffix in ALLOWED_IMAGE)
    if not valid or doc.file_size is None or doc.file_size > MAX_BYTES:
        await callback.answer('Недопустимое действие.', show_alert=True)
        return
    await callback.answer()
    status = await callback.message.answer('⏳ Обрабатываю файл…')
    try:
        with tempfile.TemporaryDirectory(prefix='fileshape_') as directory:
            folder = Path(directory)
            source = folder / ('source' + suffix)
            await bot.download(doc, destination=source)
            if source.stat().st_size > MAX_BYTES:
                raise ValueError('File exceeds size limit')
            if action == 'pdf:first':
                target = folder / 'first_page.pdf'
                await asyncio.to_thread(split_pdf, source, target)
            else:
                fmt = action.split(':', 1)[1]
                ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[fmt]
                target = folder / ('converted' + ext)
                await asyncio.to_thread(convert_image, source, target, fmt)
            await callback.message.answer_document(FSInputFile(target), caption='✅ Готово · FileShape')
    except Exception:
        logging.exception('File processing failed')
        await callback.message.answer('Не удалось обработать файл. Проверь формат и попробуй другой файл.')
    finally:
        await status.delete()


async def main():
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
