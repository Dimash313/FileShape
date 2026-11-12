# FileShape

A Telegram file editor and converter by **IhsanSoft**, written in Python with aiogram 3.

## Implemented (v0.2)

Send a file in a **private chat** with the bot; the bot shows actions appropriate to the file.

**PDF**
- Show number of pages.
- Extract the first page or select pages (for example: `1,3-5`).
- Rotate all pages 90 degrees clockwise.
- Combine 2–5 PDFs in the order they are sent (`/done` to finish, `/cancel` to cancel).

**Images**
- Convert JPG, PNG and WebP to JPG/PNG/WebP or to a one-page PDF.
- Optimize to WebP with quality 72 (smaller output is *not* guaranteed).
- Accept images as Telegram photos or as documents; sending as a document preserves original quality.

**Limits and privacy**
- Max incoming file size: 20 MB (standard Telegram Bot API download limit).
- Merge limit: 60 MB total, 5 PDFs, 250 total pages.
- Processing concurrency: up to 3 operations.
- Source and result files reside in temporary folders and are deleted after processing.
- The bot has no database or persistent user-file storage.

## Run locally

1. Install Python **3.11 or newer**.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`.
4. Put the token created in BotFather into `.env` as `BOT_TOKEN=...`. **Never commit your actual token.**
5. Start the bot: `python main.py`.

The process must remain running for long polling to respond. GitHub is only source control; creating a repository does not host the bot.

## Tests

```bash
python -m unittest discover -s tests -v
```

Automated tests also run in GitHub Actions for commits to `main`.

## Roadmap

- More advanced PDF manipulation and batch tools
- Document, audio and archive conversion and inspection
- More polished interface and PRO subscription infrastructure
- Cloud hosting, production limits, monitoring and persistent job management

These roadmap features are **not implemented yet**.
