# FileShape

A Telegram file utility by IhsanSoft, built with Python and aiogram 3.

## MVP features
- Send a PDF as a Telegram document and extract its first page.
- Send JPG, PNG or WebP as a document and convert between these formats.
- Temporary working directories are removed after processing.
- File upload limit: 20 MB (initial setting).

## Setup
1. Install Python 3.11+ and dependencies: `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN` in `.env`. **Never commit this token.**
4. Start: `python main.py`.

The bot runs with long polling, so it must remain running on a host to respond. It is not yet deployed. Advanced editing, multi-file PDF merge, archive/audio operations, subscriptions, and production hardening are planned, not implemented.
