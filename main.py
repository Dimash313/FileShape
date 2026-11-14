"""FileShape: Telegram-based PDF and image toolbox."""
import asyncio
from contextlib import suppress, asynccontextmanager
import logging
import os
from pathlib import Path
import tempfile

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
    LabeledPrice,
    PreCheckoutQuery,
)

from config import get_settings
from api.stars_auth import support_username
from services.bot_access import check_processing_access
from services.bot_operations import (
    BotOperationQuotaExceeded, BotOperationUnavailable,
    reserve_bot_operation, settle_bot_operation,
)
from services.campaign_bridge import forward_campaign_join
from services.stars_reconciliation import star_reconciliation_loop
from services.stars_bridge import (
    StarsBridgeUnavailable, checkout_enabled, create_stars_quote,
    approve_stars_checkout, confirm_stars_payment, confirm_stars_refund,
)
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


def miniapp_keyboard() -> InlineKeyboardMarkup | None:
    url = os.getenv("MINIAPP_URL", "").strip()
    if not url.startswith("https://") or " " in url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✨ Открыть FileShape Studio",
                web_app=WebAppInfo(url=url),
            )
        ]]
    )


def buttons(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=code) for label, code in row]
            for row in rows
        ]
    )


NAV_CATEGORIES = {
    "pdf": ("📄 PDF", "Объединение, страницы, поворот и удаление страниц."),
    "image": ("🖼 Фото", "Конвертация JPG, PNG, WebP и PDF; оптимизация WebP."),
    "audio": ("🎧 Аудио", "MP3, OGG, WAV и информация о записи."),
    "documents": ("📝 Документы", "Конвертация DOCX ↔ TXT."),
    "archive": ("📦 Архивы", "Создание, просмотр и распаковка ZIP."),
}


def home_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [("🧰 Инструменты", "nav:tools"), ("👤 Профиль", "nav:profile")],
        [("💎 Тарифы", "nav:plans"), ("❔ Помощь", "nav:help")],
    ]
    keyboard = buttons(rows)
    studio = miniapp_keyboard()
    if studio:
        keyboard.inline_keyboard.insert(0, studio.inline_keyboard[0])
    return keyboard


def home_text() -> str:
    return (
        "📁 FileShape\\n"
        "Всё для работы с файлами в Telegram.\\n\\n"
        "Конвертируй, сжимай и редактируй файлы.\\n"
        "Отправь файл в этот чат или открой инструменты ниже.\\n\\n"
        "📎 Файл до 20 МБ · /cancel — отменить операцию.\\n"
        "Для возврата в меню: /menu."
    )


def navigation_keyboard() -> InlineKeyboardMarkup:
    return buttons([
        [("📄 PDF", "nav:pdf"), ("🖼 Фото", "nav:image")],
        [("🎧 Аудио", "nav:audio"), ("📝 Документы", "nav:documents")],
        [("📦 Архивы", "nav:archive")],
        [("🏠 Главное меню", "nav:home")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return buttons([[("🧰 Все инструменты", "nav:tools"), ("🏠 Главное меню", "nav:home")]])


STARS_SKUS = {
    "pro_30d": ("FileShape Pro · 30 дней", "До 100 операций в сутки UTC", 149),
    "pack_10": ("10 операций FileShape", "Дополнительные операции без срока действия", 19),
    "pack_30": ("30 операций FileShape", "Дополнительные операции без срока действия", 49),
}

# Change the version whenever purchase terms change. Old consent buttons
# must fail closed rather than authorize a purchase under updated terms.
STARS_TERMS_VERSION = "1"


def stars_purchase_terms() -> str:
    contact = support_username() or "контакт пока не настроен (продажи выключены)"
    return (
        "📄 Условия покупки FileShape · версия " + STARS_TERMS_VERSION + "\\n\\n"
        "• Услуга: обработка поддерживаемых файлов в Telegram. "
        "Доступность отдельных преобразований зависит от формата и размера файла.\\n"
        "• Free: 10 успешных операций в сутки UTC, 1 активная задача. "
        "Pro: 100 операций в сутки UTC, до 3 одновременных задач на 30 суток. "
        "Новый Pro продлевает действующий. Автосписаний нет.\\n"
        "• Пакеты: 10 операций — 19 ⭐; 30 операций — 49 ⭐; "
        "без установленной даты окончания. Pro на 30 суток — 149 ⭐. "
        "После оплаты лимиты обновляются в серверном профиле.\\n"
        "• Ограничение размера загружаемого файла в боте — 20 МБ "
        "для Free и Pro. Неудачная обработка не должна расходовать операцию.\\n"
        "• Файлы временно обрабатываются и удаляются после задачи. "
        "Не отправляй пароли, ключи и другие секреты.\\n"
        "• По вопросам платежей, технических ошибок и возвратов: "
        + contact + " или /paysupport. Возвраты рассматриваются через "
        "официальный механизм Telegram Stars. Telegram не отвечает за "
        "обслуживание покупок у разработчика FileShape.\\n\\n"
        "Покупка создаётся только после явного подтверждения согласия "
        "с этими условиями. Оплата сама по себе не начинается от нажатия кнопки."
    )


def stars_terms_keyboard(sku: str) -> InlineKeyboardMarkup:
    if not checkout_enabled() or sku not in STARS_SKUS:
        return back_keyboard()
    return buttons([
        [("✅ Прочитал и согласен", f"buy:agree:{STARS_TERMS_VERSION}:{sku}")],
        [("✖️ Отмена", "nav:plans")],
    ])


def plans_keyboard() -> InlineKeyboardMarkup:
    if not checkout_enabled():
        return back_keyboard()
    return buttons([
        [("💎 Pro · 149 ⭐", "buy:pro_30d")],
        [("10 операций · 19 ⭐", "buy:pack_10"), ("30 операций · 49 ⭐", "buy:pack_30")],
        [("🏠 Главное меню", "nav:home")],
    ])


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

def classify_extension(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return {
        ".docx": "docx", ".txt": "txt", ".zip": "archive",
    }.get(suffix, "other")


def attachment(message: Message):
    """Return Telegram file, extension, category, byte count (or None)."""
    if message.document:
        document = message.document
        suffix = Path(document.file_name or "").suffix.lower()
        category = classify_extension(suffix)
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


def received_filename(message: Message) -> str:
    if message.document:
        return message.document.file_name or "file.bin"
    if message.voice:
        return "voice.ogg"
    if message.audio:
        extension = attachment(message)[1]
        return message.audio.file_name or ("audio" + extension)
    if message.photo:
        return "photo.jpg"
    return "file.bin"


def size_allowed(size: int | None) -> bool:
    return size is not None and 0 < size <= MAX_BYTES


def check_download(path: Path) -> None:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("File is too large")


async def send_result(message: Message, path: Path, caption: str = "✅ Готово · FileShape"):
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("Result is too large to send")
    kind = classify_extension(path.suffix)
    can_reprocess = path.stat().st_size <= MAX_BYTES
    # Telegram's standard Bot API cannot download a bot file above 20 MB.
    return await message.answer_document(
        FSInputFile(path),
        caption="FileShape · " + caption + (
            "" if can_reprocess else "\\n⚠️ Результат больше 20 МБ: повторная обработка недоступна."
        ),
        reply_markup=file_menu(kind) if can_reprocess else None,
    )


async def remove_status(message: Message) -> None:
    with suppress(Exception):
        await message.delete()


async def allow_processing(message: Message, bot: Bot, actor_id: int) -> bool:
    """Authorize before any file download/worker or multi-file state transition.

    Channel/Premium state lives only in the API process; bot never opens SQLite.
    """
    if (type(actor_id) is not int or actor_id <= 0
            or message.chat.type != "private" or message.chat.id != actor_id):
        await message.answer("Обработка доступна только для твоих файлов в личном чате.")
        return False
    decision = await check_processing_access(actor_id, bot.token)
    if decision == "allowed":
        return True
    if decision == "subscription_required":
        await message.answer(
            "🔒 Для новой обработки нужна подписка на обязательные каналы. "
            "После подписки повтори действие."
        )
    else:
        await message.answer(
            "Проверка подписки временно недоступна. "
            "Файл не обрабатывался — попробуй позже."
        )
    return False


@asynccontextmanager
async def metered_bot_work(actor_id: int, bot: Bot):
    """An operation counts only after the complete Telegram response is sent.

    A failed download, conversion or Telegram delivery releases the reservation.
    The API reconciles abandoned leases if a worker crashes or disconnects.
    """
    job_id = await reserve_bot_operation(actor_id, bot.token)
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        try:
            await settle_bot_operation(actor_id, bot.token, job_id, succeeded)
        except BotOperationUnavailable:
            # Never claim success on uncertain accounting. API lease expiry
            # eventually releases any unresolved reservation.
            logger.error("Bot operation settlement unavailable")


@router.message(CommandStart())
@router.message(Command("menu"))
async def start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("Открой личный чат с FileShape для работы с файлами.")
        return
    await state.clear()
    await message.answer(home_text(), reply_markup=home_keyboard())


@router.message(Command("help", "tools"))
async def help_message(message: Message):
    await message.answer(
        "🧰 FileShape · Инструменты\\n\\n"
        "Выбери раздел или просто отправь файл.\\n"
        "Для отмены текущей операции: /cancel.",
        reply_markup=navigation_keyboard(),
    )


@router.message(Command("profile"))
async def profile_message(message: Message):
    await message.answer(
        "👤 Профиль FileShape\\n\\n"
        "Операции учитываются сервером: Free — 10 успешных действий за сутки UTC. "
        "Персональный остаток и дата окончания Pro появятся здесь в обновлении профиля.",
        reply_markup=back_keyboard(),
    )


@router.message(Command("terms"))
async def terms_message(message: Message):
    await message.answer(stars_purchase_terms(), reply_markup=back_keyboard())


@router.message(Command("plans"))
async def plans_message(message: Message):
    await message.answer(
        "💎 Тарифы FileShape\\n\\n"
        "Free: 10 успешных операций в сутки UTC, один активный запрос.\\n"
        "Pro: 100 в сутки и до трёх одновременных — после активации тарифа.\\n"
        + ("Покупка Pro и пакетов через Telegram Stars доступна ниже. " if checkout_enabled()
         else "Покупка Pro и пакетов через Telegram Stars пока недоступна. ")
        + "Лимит размера файла сейчас — 20 МБ.",
        reply_markup=plans_keyboard(),
    )


@router.callback_query(F.data.startswith("nav:"))
async def navigate(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer("Открой личный чат с ботом.", show_alert=True)
        return
    if callback.message.chat.type != "private" or callback.message.chat.id != callback.from_user.id:
        await callback.answer("Это меню доступно только в твоём личном чате.", show_alert=True)
        return
    section = (callback.data or "")[4:]
    if section == "home":
        await state.clear()
        text, markup = home_text(), home_keyboard()
    elif section == "tools":
        text, markup = "🧰 Инструменты FileShape\\n\\nВыбери категорию или отправь файл.", navigation_keyboard()
    elif section in NAV_CATEGORIES:
        title, description = NAV_CATEGORIES[section]
        text = f"{title}\\n\\n{description}\\n\\nОтправь файл в этот чат — бот покажет доступные действия."
        markup = back_keyboard()
    elif section == "profile":
        text = ("👤 Профиль FileShape\\n\\n"
                "Сервер учитывает операции: Free — 10 успешных действий в сутки UTC. "
                "Персональный остаток появится здесь в обновлении профиля.")
        markup = back_keyboard()
    elif section == "plans":
        text = (
            "💎 Тарифы FileShape\\n\\n"
            "Free: 10 операций в сутки UTC. Pro: 100 при активной подписке.\\n"
            + ("Выбери тариф ниже. Перед счётом прочитай /terms. Оплата через Telegram Stars."
               if checkout_enabled()
               else "Оплата Telegram Stars и покупка пакетов пока недоступны.")
        )
        markup = plans_keyboard()
    elif section == "help":
        text = ("❔ Как пользоваться\\n\\n"
                "1. Отправь PDF, изображение, аудио, DOCX, TXT или ZIP.\\n"
                "2. Выбери действие под файлом.\\n"
                "3. Получи результат в этом чате.\\n\\n"
                "Отмена: /cancel · Главное меню: /menu.")
        markup = back_keyboard()
    else:
        await callback.answer("Раздел не найден.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


def _private_stars_callback(callback: CallbackQuery) -> bool:
    return (
        isinstance(callback.message, Message)
        and callback.message.chat.type == "private"
        and callback.message.chat.id == callback.from_user.id
    )


@router.callback_query(F.data.startswith("buy:agree:"))
async def buy_stars_after_terms(callback: CallbackQuery, bot: Bot):
    """Invoice only after the user explicitly accepts the current terms."""
    if not _private_stars_callback(callback):
        await callback.answer("Открой личный чат с ботом.", show_alert=True)
        return
    data = (callback.data or "").split(":")
    if (len(data) != 4 or data[:2] != ["buy", "agree"]
            or data[2] != STARS_TERMS_VERSION
            or not checkout_enabled() or data[3] not in STARS_SKUS):
        await callback.answer("Счёт недоступен. Открой /plans и прочитай условия заново.",
                              show_alert=True)
        return
    sku = data[3]
    await callback.answer()
    try:
        quote = await create_stars_quote(callback.from_user.id, bot.token, sku)
    except StarsBridgeUnavailable:
        await callback.message.answer("Не удалось подготовить счёт. Операция не оплачена.")
        return
    title, description, price = STARS_SKUS[sku]
    if quote["amount"] != price:
        logger.error("Unexpected Stars price for %s", sku)
        await callback.message.answer("Тариф временно недоступен. Операция не оплачена.")
        return
    try:
        await callback.message.answer_invoice(
            title=title, description=description,
            payload="fileshape:" + quote["order_id"],
            currency="XTR", prices=[LabeledPrice(label=title, amount=price)],
            provider_token="", start_parameter="",
        )
    except Exception:
        logger.exception("FileShape invoice delivery failed")
        await callback.message.answer("Не удалось отправить счёт. Операция не оплачена.")


@router.callback_query(F.data.startswith("buy:"))
async def buy_stars_product(callback: CallbackQuery, bot: Bot):
    """Choosing a tariff opens conditions, it never creates an invoice."""
    if not _private_stars_callback(callback):
        await callback.answer("Открой личный чат с ботом.", show_alert=True)
        return
    sku = (callback.data or "").removeprefix("buy:")
    if not checkout_enabled() or sku not in STARS_SKUS:
        await callback.answer("Покупки временно недоступны.", show_alert=True)
        return
    await callback.answer()
    name, _, price = STARS_SKUS[sku]
    await callback.message.answer(
        f"Выбран тариф: {name} · {price} ⭐\\n\\n"
        + stars_purchase_terms(),
        reply_markup=stars_terms_keyboard(sku),
    )


@router.pre_checkout_query()
async def stars_precheckout(query: PreCheckoutQuery, bot: Bot):
    """A positive pre-checkout response never grants access or a balance."""
    payload = query.invoice_payload
    order_id = payload.removeprefix("fileshape:") if payload.startswith("fileshape:") else ""
    approved = False
    if order_id and checkout_enabled():
        try:
            approved = await approve_stars_checkout(
                query.from_user.id, bot.token,
                order_id, query.total_amount, query.currency,
            )
        except StarsBridgeUnavailable:
            logger.error("Stars pre-checkout verification unavailable")
    await query.answer(
        ok=approved,
        error_message=None if approved else "Проверка заказа недоступна. Попробуй позже.",
    )


@router.message(F.successful_payment)
async def stars_payment_received(message: Message, bot: Bot):
    """Only the Telegram-delivered successful_payment event can grant paid value."""
    payment = message.successful_payment
    if (
        payment is None or message.from_user is None
        or message.chat.type != "private"
        or message.chat.id != message.from_user.id
    ):
        logger.error("Unexpected Telegram Stars receipt context")
        return
    payload = payment.invoice_payload
    order_id = payload.removeprefix("fileshape:") if payload.startswith("fileshape:") else ""
    try:
        result = await confirm_stars_payment(
            message.from_user.id, bot.token, order_id, payment.total_amount,
            payment.currency, payment.telegram_payment_charge_id,
        )
    except StarsBridgeUnavailable:
        logger.error("Stars payment needs reconciliation; no false confirmation sent")
        await message.answer(
            "Платёж получен Telegram, но подтверждение доступа пока не завершено. "
            "Сохрани чек и обратись в поддержку через /paysupport."
        )
        return
    if result["status"] == "fulfilled":
        await message.answer("✅ Покупка подтверждена. Доступ или пакет операций начислен.")


@router.message(F.refunded_payment)
async def stars_refund_received(message: Message, bot: Bot):
    """Revoke on Telegram's own refunded_payment service event, not user text."""
    refunded = message.refunded_payment
    if refunded is None or message.chat.type != "private" or message.chat.id <= 0:
        return
    payload = refunded.invoice_payload
    order_id = payload.removeprefix("fileshape:") if isinstance(payload, str) and payload.startswith("fileshape:") else ""
    if (len(order_id) != 32 or any(ch not in "0123456789abcdef" for ch in order_id)
            or refunded.currency != "XTR"
            or type(refunded.total_amount) is not int or refunded.total_amount <= 0):
        logger.warning("Ignoring unexpected Telegram payment refund")
        return
    try:
        result = await confirm_stars_refund(
            message.chat.id, bot.token, refunded.telegram_payment_charge_id,
        )
    except StarsBridgeUnavailable:
        logger.error("Telegram refund received; API reversal awaiting reconciliation")
        return
    if result["status"] == "refunded":
        await message.answer("Возврат Stars подтверждён. Доступ и операции пересчитаны.")


@router.message(Command("paysupport"))
async def stars_payment_support(message: Message):
    contact = support_username()
    await message.answer(
        ("Поддержка платежей FileShape: " + contact + ". Сохрани чек Telegram. "
         if contact is not None else
         "Контакт платёжной поддержки пока не настроен. Покупки отключены. ")
        + "Никому не сообщай пароли или коды."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✖️ Операция отменена. Отправь новый файл.")


async def run_merge(message: Message, bot: Bot, state: FSMContext, actor_id: int):
    if await state.get_state() != MergeState.collecting.state:
        await message.answer("Сначала выбери «Объединить» для PDF.")
        return
    data = await state.get_data()
    items = data.get("pdfs", [])
    if len(items) < 2:
        await message.answer("Добавь ещё хотя бы один PDF, затем нажми «Готово».")
        return
    if not await allow_processing(message, bot, actor_id):
        return
    status = await message.answer("⏳ Объединяю PDF…")
    try:
        async with processing_slots, metered_bot_work(actor_id, bot):
            await state.clear()
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
    except BotOperationQuotaExceeded:
        await message.answer("Лимит операций исчерпан или предыдущая операция ещё выполняется.")
    except BotOperationUnavailable:
        await message.answer("Учёт операций временно недоступен. Файлы не обрабатывались.")
    except ValueError as error:
        await message.answer(f"Не удалось объединить: {error}. Начни заново.")
    except Exception:
        logger.exception("PDF merge failed")
        await message.answer("Не удалось объединить PDF. Проверь, что файлы не повреждены." )
    finally:
        await remove_status(status)


@router.message(MergeState.collecting, Command("done"))
async def done_command(message: Message, bot: Bot, state: FSMContext):
    await run_merge(message, bot, state, message.from_user.id if message.from_user else -1)


@router.callback_query(F.data == "merge:done")
async def done_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    if isinstance(callback.message, Message):
        await run_merge(callback.message, bot, state, callback.from_user.id)


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


async def run_zip_bundle(message: Message, bot: Bot, state: FSMContext, actor_id: int):
    if await state.get_state() != ZipState.collecting.state:
        await message.answer("Сначала выбери «Собрать ZIP» у файла.")
        return
    data = await state.get_data()
    items = data.get("zip_files", [])
    if len(items) < 2:
        await message.answer("Добавь ещё один файл, затем нажми «Готово».")
        return
    if not await allow_processing(message, bot, actor_id):
        return
    status = await message.answer("⏳ Создаю ZIP…")
    try:
        async with processing_slots, metered_bot_work(actor_id, bot):
            await state.clear()
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
    except BotOperationQuotaExceeded:
        await message.answer("Лимит операций исчерпан или предыдущая операция ещё выполняется.")
    except BotOperationUnavailable:
        await message.answer("Учёт операций временно недоступен. Файлы не обрабатывались.")
    except ValueError as error:
        await message.answer(f"Не удалось собрать ZIP: {error}.")
    except Exception:
        logger.exception("ZIP creation failed")
        await message.answer("Не удалось собрать ZIP. Попробуй файлы поменьше.")
    finally:
        await remove_status(status)


@router.message(ZipState.collecting, Command("done"))
async def done_zip_command(message: Message, bot: Bot, state: FSMContext):
    await run_zip_bundle(message, bot, state, message.from_user.id if message.from_user else -1)


@router.callback_query(F.data == "bundle:done")
async def done_zip_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    if isinstance(callback.message, Message):
        await run_zip_bundle(callback.message, bot, state, callback.from_user.id)


@router.callback_query(F.data == "bundle:cancel")
async def cancel_zip_button(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != ZipState.collecting.state:
        await callback.answer("Эта операция уже завершена.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Отменено")
    if isinstance(callback.message, Message):
        await callback.message.answer("✖️ Создание ZIP отменено.")


@router.message(ZipState.collecting, F.document | F.photo | F.audio | F.voice)
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
        "name": received_filename(message),
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
    actor_id = message.from_user.id if message.from_user else -1
    if not await allow_processing(message, bot, actor_id):
        return
    status = await message.answer("⏳ Обрабатываю страницы PDF…")
    try:
        async with processing_slots, metered_bot_work(actor_id, bot):
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
    except BotOperationQuotaExceeded:
        await message.answer("Лимит операций исчерпан или предыдущая операция ещё выполняется.")
    except BotOperationUnavailable:
        await message.answer("Учёт операций временно недоступен. Файлы не обрабатывались.")
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
        f"{label} · {size / 1024 / 1024:.1f} МБ\n"
        f"{received_filename(message)[:70]}\n\n"
        "Выбери действие ↓",
        reply_markup=file_menu(category),
        reply_to_message_id=message.message_id,
    )


@router.callback_query(F.data.startswith(("pdf:", "img:", "docx:", "txt:", "zip:", "audio:")))
async def run_action(callback: CallbackQuery, bot: Bot, state: FSMContext):
    action = callback.data or ""
    if not isinstance(callback.message, Message):
        await callback.answer("Отправь файл заново.", show_alert=True)
        return
    # Original user upload: menu replies to the source message.
    # Generated result: the bot document itself carries the next menu.
    result_message = (
        callback.message.document is not None
        and (callback.message.caption or "").startswith("FileShape · ")
        and callback.message.from_user is not None
        and callback.message.from_user.is_bot
    )
    origin = callback.message if result_message else callback.message.reply_to_message
    if (
        callback.message.chat.type != "private"
        or callback.message.chat.id != callback.from_user.id
        or not origin
        or not origin.from_user
        or (not result_message and origin.from_user.id != callback.from_user.id)
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
    if not await allow_processing(callback.message, bot, callback.from_user.id):
        return
    if action == "zip:create":
        await state.set_state(ZipState.collecting)
        suggested_name = received_filename(origin)
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
        async with processing_slots, metered_bot_work(callback.from_user.id, bot):
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
    except BotOperationQuotaExceeded:
        await callback.message.answer("Лимит операций исчерпан или предыдущая операция ещё выполняется.")
    except BotOperationUnavailable:
        await callback.message.answer("Учёт операций временно недоступен. Файл не обрабатывался.")
    except ValueError as error:
        await callback.message.answer(f"Не удалось обработать файл: {error}.")
    except Exception:
        logger.exception("File processing failed")
        await callback.message.answer("Не удалось обработать файл. Проверь формат и попробуй снова.")
    finally:
        await remove_status(status)


@router.chat_member()
async def on_campaign_chat_member(event: ChatMemberUpdated, bot: Bot):
    """Process only Telegram-delivered membership updates, not user messages."""
    try:
        await forward_campaign_join(event, bot.token)
    except Exception:
        logger.exception("Campaign join forwarding failed")


async def main():
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    # Telegram's getStarTransactions ledger is independently authoritative.
    # Recover successful_payment events lost while the API/bot was offline
    # without accessing the API-owned SQLite from the bot container.
    reconciliation = asyncio.create_task(star_reconciliation_loop(bot))
    try:
        await dp.start_polling(
            bot, allowed_updates=["message", "callback_query", "chat_member", "pre_checkout_query"],
        )
    finally:
        reconciliation.cancel()
        with suppress(asyncio.CancelledError):
            await reconciliation
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
