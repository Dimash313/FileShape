"""Authenticated, short-lived file transformations for the FileShape Mini App.

Run one API worker behind an HTTPS reverse proxy. No user files are persisted.
"""
import asyncio
from collections import defaultdict, deque
import logging
import mimetypes
import os
from pathlib import Path
import tempfile
import time

from fastapi import Depends, FastAPI, File as FileField, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from api.auth import InvalidInitData, verify_init_data
from api.ingress import UploadIngressGuard
from api.observability import RequestTrace
from api.readiness import readiness_status
from api.worker_runner import WorkerFailed, WorkerTimeout, run_worker
from api.workspaces import Workspace, cleanup_orphans
from config import get_settings
from services.audio_tools import AUDIO_EXTENSIONS, OUTPUT_FORMATS, convert_audio, probe_audio
from services.archive_tools import inspect_zip
from services.document_tools import docx_to_txt, read_docx_text, txt_info, txt_to_docx
from services.image_bundle import MIN_IMAGES, MAX_IMAGES, images_to_pdf
from services.upload_validation import validate_upload
from services.file_tools import (
    IMAGE_FORMATS, compress_image, convert_image, extract_pdf_pages,
    pdf_page_count, remove_pdf_pages, rotate_pdf,
)

logger = logging.getLogger(__name__)
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_RESULT_BYTES = 45 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_INPUT_BYTES + 1024 * 1024
RATE_LIMIT_PER_MINUTE = 12

SUPPORTED: dict[str, set[str]] = {
    "image": {"img:JPEG", "img:PNG", "img:WEBP", "img:PDF", "img:compress"},
    "pdf": {"pdf:rotate", "pdf:first", "pdf:extract", "pdf:remove", "pdf:info"},
    "audio": {"audio:mp3", "audio:ogg", "audio:wav", "audio:info"},
    "docx": {"docx:txt", "docx:info"},
    "txt": {"txt:docx", "txt:info"},
    "archive": {"zip:list"},
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
api = FastAPI(title="FileShape Mini App API", docs_url=None, redoc_url=None, openapi_url=None)
allowed_origin = os.environ.get("MINIAPP_ORIGIN", "").strip().rstrip("/")
if allowed_origin:
    if not allowed_origin.startswith("https://") or "*" in allowed_origin:
        raise RuntimeError("MINIAPP_ORIGIN must be a single HTTPS origin")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[allowed_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Telegram-Init-Data", "Content-Type"],
    )

def configured_worker_capacity() -> int:
    """Bound concurrent workers; deploy with sufficient RAM for this setting."""
    raw = os.environ.get("FILESHAPE_MAX_CONCURRENT_JOBS", "3")
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError("FILESHAPE_MAX_CONCURRENT_JOBS must be an integer") from None
    if not 1 <= value <= 10:
        raise RuntimeError("FILESHAPE_MAX_CONCURRENT_JOBS must be between 1 and 10")
    return value


MAX_CONCURRENT_JOBS = configured_worker_capacity()
slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
limiter_lock = asyncio.Lock()
recent_requests: dict[int, deque[float]] = defaultdict(deque)


def file_kind(filename: str) -> tuple[str, str]:
    suffix = Path(filename.replace("\\", "/")).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image", suffix
    if suffix == ".pdf":
        return "pdf", suffix
    if suffix in AUDIO_EXTENSIONS:
        return "audio", suffix
    if suffix in {".docx", ".txt"}:
        return suffix[1:], suffix
    if suffix == ".zip":
        return "archive", suffix
    return "other", suffix


api.add_middleware(
    UploadIngressGuard,
    max_bytes=MAX_REQUEST_BYTES,
    paths={"/api/v1/convert", "/api/v1/images/pdf"},
)
# Outer middleware also observes requests rejected before multipart parsing.
api.add_middleware(RequestTrace)


def authenticated_user(
    raw: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> int:
    try:
        return verify_init_data(raw, get_settings().bot_token)
    except InvalidInitData:
        raise HTTPException(status_code=401, detail="Открой приложение внутри Telegram заново") from None


async def enforce_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    async with limiter_lock:
        window = recent_requests[user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Слишком много запросов. Повтори позже.")
        window.append(now)
        # Prevent unused per-user queues from accumulating forever.
        if len(recent_requests) > 10_000:
            for key in list(recent_requests):
                if not recent_requests[key] or now - recent_requests[key][-1] > 120:
                    del recent_requests[key]


@api.on_event("startup")
async def remove_abandoned_workspaces():
    # Only workspaces older than one hour and without a held lock.
    await asyncio.to_thread(cleanup_orphans)


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/ready")
async def ready():
    result = await asyncio.to_thread(readiness_status)
    return JSONResponse(
        result,
        status_code=200 if result["status"] == "ready" else 503,
        headers={"Cache-Control": "no-store"},
    )


@api.get("/api/v1/session")
async def session(user_id: int = Depends(authenticated_user)):
    return {"ok": True, "user_id": user_id, "max_upload_bytes": MAX_INPUT_BYTES}


def _info_action(source: Path, action: str) -> dict | None:
    if action == "pdf:info":
        return {"info": {"pages": pdf_page_count(source)}}
    if action == "audio:info":
        return {"info": probe_audio(source)}
    if action == "docx:info":
        _, info = read_docx_text(source)
        return {"info": info}
    if action == "txt:info":
        return {"info": txt_info(source)}
    if action == "zip:list":
        return {"info": inspect_zip(source)}
    return None


def _transform(source: Path, output_dir: Path, action: str, pages: str) -> Path:
    if action.startswith("img:"):
        if action == "img:compress":
            target = output_dir / "optimized.webp"
            compress_image(source, target)
        else:
            fmt = action.split(":", 1)[1]
            target = output_dir / ("converted" + IMAGE_FORMATS[fmt])
            convert_image(source, target, fmt)
    elif action.startswith("audio:"):
        fmt = action.split(":", 1)[1]
        target = output_dir / ("converted" + OUTPUT_FORMATS[fmt])
        convert_audio(source, target, fmt)
    elif action == "pdf:rotate":
        target = output_dir / "rotated.pdf"
        rotate_pdf(source, target, 90)
    elif action in {"pdf:first", "pdf:extract", "pdf:remove"}:
        target = output_dir / "result.pdf"
        if action == "pdf:remove":
            remove_pdf_pages(source, target, pages)
        else:
            extract_pdf_pages(source, target, "1" if action == "pdf:first" else pages)
    elif action == "docx:txt":
        target = output_dir / "converted.txt"
        docx_to_txt(source, target)
    elif action == "txt:docx":
        target = output_dir / "converted.docx"
        txt_to_docx(source, target)
    else:
        raise ValueError("Недопустимая операция")
    return target


@api.post("/api/v1/convert")
async def convert(
    upload: UploadFile = FileField(...),
    action: str = Form(...),
    pages: str = Form(default=""),
    user_id: int = Depends(authenticated_user),
):
    kind, suffix = file_kind(upload.filename or "")
    if action not in SUPPORTED.get(kind, set()):
        raise HTTPException(status_code=422, detail="Эта операция недоступна для выбранного файла")
    if len(pages) > 90:
        raise HTTPException(status_code=422, detail="Слишком длинный диапазон страниц")
    await enforce_rate_limit(user_id)
    try:
        await asyncio.wait_for(slots.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Сервер занят. Повтори позже.") from None

    work = Workspace(prefix="fileshape_api_")
    try:
        source = Path(work.name) / ("source" + suffix)
        read_bytes = 0
        with source.open("wb") as output:
            while True:
                chunk = await upload.read(64 * 1024)
                if not chunk:
                    break
                read_bytes += len(chunk)
                if read_bytes > MAX_INPUT_BYTES:
                    raise HTTPException(status_code=413, detail="Максимальный размер файла — 20 МБ")
                output.write(chunk)
        if read_bytes == 0:
            raise HTTPException(status_code=422, detail="Пустой файл")
        result = await run_worker({
            "operation": "single", "work": work.name,
            "suffix": suffix, "action": action, "pages": pages,
        })
        if "info" in result:
            work.cleanup()
            return JSONResponse(result["info"], headers={"Cache-Control": "no-store"})

        target = Path(work.name) / result["filename"]
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError("Пустой результат")
        if target.stat().st_size > MAX_RESULT_BYTES:
            raise HTTPException(status_code=413, detail="Результат слишком большой")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return FileResponse(
            target,
            filename=target.name,
            media_type=content_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(work.cleanup),
        )
    except asyncio.CancelledError:
        # Cancellation does not inherit from Exception. Remove partial uploads
        # and outputs before propagating cancellation to the ASGI server.
        work.cleanup()
        raise
    except HTTPException:
        work.cleanup()
        raise
    except WorkerTimeout as exc:
        work.cleanup()
        raise HTTPException(status_code=504, detail=str(exc)) from None
    except ValueError as exc:
        work.cleanup()
        raise HTTPException(status_code=422, detail=str(exc)[:200]) from None
    except Exception:
        work.cleanup()
        logger.error("FileShape API processing failed")
        raise HTTPException(status_code=422, detail="Не удалось прочитать или обработать файл") from None
    finally:
        slots.release()
        await upload.close()


@api.post("/api/v1/images/pdf")
async def multi_image_pdf(
    uploads: list[UploadFile] = FileField(...),
    user_id: int = Depends(authenticated_user),
):
    """Convert 2–8 pictures to one PDF without storing user data."""
    if not MIN_IMAGES <= len(uploads) <= MAX_IMAGES:
        raise HTTPException(status_code=422, detail="Выбери от 2 до 8 изображений")
    for upload in uploads:
        kind, _ = file_kind(upload.filename or "")
        if kind != "image":
            raise HTTPException(status_code=422, detail="Поддерживаются только JPG, PNG и WebP")
    await enforce_rate_limit(user_id)
    try:
        await asyncio.wait_for(slots.acquire(), timeout=1.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Сервер занят. Попробуй позже.") from None

    work = Workspace(prefix="fileshape_batch_")
    try:
        paths = []
        total = 0
        for index, upload in enumerate(uploads):
            suffix = file_kind(upload.filename or "")[1]
            path = Path(work.name) / f"image_{index}{suffix}"
            count = 0
            with path.open("wb") as output:
                while True:
                    chunk = await upload.read(64 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    total += len(chunk)
                    if total > MAX_INPUT_BYTES:
                        raise HTTPException(status_code=413, detail="Общий размер файлов превышает 20 МБ")
                    output.write(chunk)
            if count == 0:
                raise HTTPException(status_code=422, detail="Обнаружен пустой файл")
            paths.append(path)

        await run_worker({
            "operation": "batch", "work": work.name,
            "suffixes": [file_kind(upload.filename or "")[1] for upload in uploads],
        })
        target = Path(work.name) / "fileshape_photos.pdf"
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError("Не удалось создать PDF")
        if target.stat().st_size > MAX_RESULT_BYTES:
            raise HTTPException(status_code=413, detail="Результат слишком большой")
        return FileResponse(
            target,
            filename=target.name,
            media_type="application/pdf",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(work.cleanup),
        )
    except asyncio.CancelledError:
        # Cancellation does not inherit from Exception. Remove partial uploads
        # and outputs before propagating cancellation to the ASGI server.
        work.cleanup()
        raise
    except HTTPException:
        work.cleanup()
        raise
    except WorkerTimeout as exc:
        work.cleanup()
        raise HTTPException(status_code=504, detail=str(exc)) from None
    except ValueError as exc:
        work.cleanup()
        raise HTTPException(status_code=422, detail=str(exc)[:200]) from None
    except Exception:
        work.cleanup()
        logger.error("Multi-image PDF failed")
        raise HTTPException(status_code=422, detail="Не удалось объединить изображения") from None
    finally:
        slots.release()
        for upload in uploads:
            await upload.close()
