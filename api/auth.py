"""Verify Telegram Mini App initData on the server, never on the client."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

MAX_INIT_DATA_LENGTH = 8192
MAX_AGE_SECONDS = 3600


class InvalidInitData(ValueError):
    pass


def verify_init_data(raw: str, bot_token: str, now: int | None = None) -> int:
    """Validate Telegram-signed launch data and return the verified user ID."""
    if not isinstance(raw, str) or not 0 < len(raw) <= MAX_INIT_DATA_LENGTH:
        raise InvalidInitData("Отсутствует авторизация Telegram")
    if not bot_token:
        raise InvalidInitData("Сервер не настроен")
    try:
        pairs = parse_qsl(
            raw, keep_blank_values=True, strict_parsing=True, max_num_fields=40
        )
    except ValueError:
        raise InvalidInitData("Некорректные данные Telegram") from None
    data = dict(pairs)
    if len(data) != len(pairs):
        raise InvalidInitData("Повторяющиеся параметры")
    signature = data.pop("hash", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        raise InvalidInitData("Отсутствует подпись Telegram")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    actual = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(actual, signature.lower()):
        raise InvalidInitData("Недействительная подпись Telegram")

    try:
        auth_date = int(data["auth_date"])
        user = json.loads(data["user"])
        user_id = user["id"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise InvalidInitData("Не удалось определить пользователя") from None
    if type(user_id) is not int or user_id <= 0:
        raise InvalidInitData("Неверный пользователь")
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > MAX_AGE_SECONDS:
        raise InvalidInitData("Сессия Telegram устарела")
    return user_id
