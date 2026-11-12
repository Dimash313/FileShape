import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    max_file_mb: int = 20


def get_settings() -> Settings:
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('BOT_TOKEN is missing. Create a local .env file.')
    return Settings(bot_token=token)
