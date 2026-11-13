"""Authenticated, short-lived file transformations for the FileShape Mini App.

Run one API worker behind an HTTPS reverse proxy. Background results are temporary and are not recovered after restart.
"""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import sqlite3
import logging
import mimetypes
import os
from pathlib import Path
import tempfile
import time

from fastapi import Depends, FastAPI, File as FileField, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from api.artifacts import ArtifactStore, ArtifactUnavailable
from api.background_jobs import BackgroundJobs
from api.admission import AdmissionQueue, QueueClosed, QueueFull, QueueTimeout
from api.auth import InvalidInitData, verify_init_data
from api.ingress import UploadIngressGuard
from api.jobs import JobCapacityExceeded, JobNotFound, JobStateError
from api.job_runtime import JobRuntime
from api.job_manager import JobManager, ManagerClosed, ManagerFull
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
        allow_headers=["X-Telegram-Init-Data", "Content-Type", "Idempotency-Key"],
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
admission = AdmissionQueue(max_waiters=20, wait_seconds=90.0)
jobs = None
job_runtime = None
metadata_maintenance = None
job_manager = None
background_jobs = None
download_slots = asyncio.Semaphore(4)
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
    paths={"/api/v1/convert", "/api/v1/images/pdf", "/api/v1/jobs"},
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


async def maintain_metadata(store):
    while True:
        await asyncio.sleep(60)
        try:
            if background_jobs is not None:
                background_jobs.artifacts.prune()
            store.prune_terminal()
            await asyncio.to_thread(cleanup_orphans)
        except (sqlite3.Error, OSError):
            logger.error("Job metadata maintenance failed")


@api.on_event("shutdown")
async def stop_accepting_conversions():
    global job_runtime, metadata_maintenance, jobs, job_manager, background_jobs
    admission.close()
    if job_manager is not None:
        await job_manager.close()
        job_manager = None
    try:
        if background_jobs is not None:
            background_jobs.close()
    finally:
        background_jobs = None
        if metadata_maintenance is not None:
            metadata_maintenance.cancel()
            await asyncio.gather(metadata_maintenance, return_exceptions=True)
            metadata_maintenance = None
        if job_runtime is not None:
            try:
                job_runtime.close()
            finally:
                job_runtime = None
        jobs = None


@api.on_event("startup")
async def remove_abandoned_workspaces():
    global admission, jobs, job_runtime, metadata_maintenance, job_manager, background_jobs
    if job_runtime is not None:
        raise RuntimeError("API lifecycle already started")
    runtime = JobRuntime(os.environ.get("FILESHAPE_STATE_DIR", "./state"))
    try:
        await asyncio.to_thread(cleanup_orphans)
        artifacts = ArtifactStore()
    except BaseException:
        runtime.close()
        raise
    if admission.closing:
        admission = AdmissionQueue(max_waiters=20, wait_seconds=90.0)
    job_manager = JobManager(MAX_CONCURRENT_JOBS, max_pending=20)
    job_runtime = runtime
    jobs = runtime.store
    background_jobs = BackgroundJobs(jobs, job_manager, artifacts, lambda payload: run_worker(payload), MAX_INPUT_BYTES, MAX_RESULT_BYTES)
    metadata_maintenance = asyncio.create_task(maintain_metadata(jobs))


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/ready")
async def ready():
    result = await asyncio.to_thread(readiness_status)
    result["checks"]["job_metadata"] = job_runtime is not None
    if job_runtime is None:
        result["status"] = "unavailable"
    return JSONResponse(
        result,
        status_code=200 if result["status"] == "ready" else 503,
        headers={"Cache-Control": "no-store"},
    )


def queue_snapshot() -> dict:
    """Coarse, per-process counts only; no user IDs or filenames."""
    # CPython asyncio.Semaphore holds the remaining permits in _value.
    # Sampled on the API event loop, this is a point-in-time view,
    # not an SLA and not an aggregate across API replicas.
    available = max(0, min(MAX_CONCURRENT_JOBS, slots._value))
    if job_manager is not None:
        return {"capacity": MAX_CONCURRENT_JOBS, "active": job_manager.active,
                "waiting": admission.waiting + job_manager.waiting,
                "waiting_limit": admission.max_waiters + 20, "accepting": not admission.closing}
    return {
        "capacity": MAX_CONCURRENT_JOBS,
        "active": MAX_CONCURRENT_JOBS - available,
        "waiting": admission.waiting,
        "waiting_limit": admission.max_waiters,
        "accepting": not admission.closing,
    }


@api.get("/api/v1/queue")
async def queue_status(user_id: int = Depends(authenticated_user)):
    await enforce_rate_limit(user_id)
    return JSONResponse(queue_snapshot(), headers={"Cache-Control": "no-store"})


@api.get("/api/v1/jobs/{job_id}")
async def job_status(job_id: str, user_id: int = Depends(authenticated_user)):
    await enforce_rate_limit(user_id)
    if jobs is None:
        raise HTTPException(status_code=503, detail="Хранилище заданий не запущено")
    try:
        item = jobs.get(job_id, user_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Задание не найдено") from None
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Хранилище заданий временно недоступно") from None
    return JSONResponse(item.public(), headers={"Cache-Control": "no-store"})


@api.post("/api/v1/jobs", status_code=202)
async def create_background_job(
    upload: UploadFile = FileField(...), action: str = Form(...),
    pages: str = Form(default=""), user_id: int = Depends(authenticated_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        kind, suffix = file_kind(upload.filename or "")
        if action not in SUPPORTED.get(kind, set()) or len(pages) > 90:
            raise HTTPException(422, "Недопустимая операция или диапазон страниц")
        await enforce_rate_limit(user_id)
        if background_jobs is None or admission.closing:
            raise HTTPException(503, "Обработчики не запущены")
        # Constants remain patchable in boundary tests; one event-loop instance.
        background_jobs.max_input = MAX_INPUT_BYTES
        background_jobs.max_result = MAX_RESULT_BYTES
        item = await background_jobs.create(upload, action, suffix, pages, user_id, idempotency_key=idempotency_key)
        return JSONResponse(item.public(), status_code=202, headers={
            "Cache-Control": "no-store", "Location": f"/api/v1/jobs/{item.job_id}",
        })
    finally:
        await upload.close()


@api.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_background_job(job_id: str, user_id: int = Depends(authenticated_user)):
    await enforce_rate_limit(user_id)
    if background_jobs is None:
        raise HTTPException(503, "Обработчики не запущены")
    try:
        item = await background_jobs.cancel(job_id, user_id)
    except JobNotFound:
        raise HTTPException(404, "Задание не найдено") from None
    except sqlite3.Error:
        raise HTTPException(503, "Хранилище временно недоступно") from None
    return JSONResponse(item.public(), headers={"Cache-Control": "no-store"})


@api.post("/api/v1/jobs/{job_id}/retry", status_code=202)
async def retry_background_job(
    job_id: str, upload: UploadFile = FileField(...), action: str = Form(...),
    pages: str = Form(default=""), user_id: int = Depends(authenticated_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        kind, suffix = file_kind(upload.filename or "")
        if action not in SUPPORTED.get(kind, set()) or len(pages) > 90:
            raise HTTPException(422, "Недопустимая операция или диапазон страниц")
        await enforce_rate_limit(user_id)
        if background_jobs is None or admission.closing:
            raise HTTPException(503, "Обработчики не запущены")
        background_jobs.max_input = MAX_INPUT_BYTES
        background_jobs.max_result = MAX_RESULT_BYTES
        try:
            item = await background_jobs.retry(job_id, upload, action, suffix, pages, user_id,
                                               idempotency_key=idempotency_key)
        except JobNotFound:
            raise HTTPException(404, "Задание не найдено") from None
        except sqlite3.Error:
            raise HTTPException(503, "Хранилище временно недоступно") from None
        return JSONResponse(item.public(), status_code=202, headers={
            "Cache-Control": "no-store", "Location": f"/api/v1/jobs/{item.job_id}",
        })
    finally:
        await upload.close()


class ResultStream(StreamingResponse):
    def __init__(self, file, size, media_type, filename):
        self.file = file
        async def chunks():
            while data := file.read(65536):
                yield data
        super().__init__(chunks(), media_type=media_type, headers={
            "Content-Length": str(size), "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{filename}"',
        })

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(120):
                await super().__call__(scope, receive, send)
        finally:
            try:
                self.file.close()
            finally:
                download_slots.release()


@api.get("/api/v1/jobs/{job_id}/result")
async def background_result(job_id: str, user_id: int = Depends(authenticated_user)):
    await enforce_rate_limit(user_id)
    if jobs is None or background_jobs is None:
        raise HTTPException(503, "Обработчики не запущены")
    try:
        item = jobs.get(job_id, user_id)  # Owner check ALWAYS precedes file access.
    except JobNotFound:
        raise HTTPException(404, "Задание не найдено") from None
    except sqlite3.Error:
        raise HTTPException(503, "Хранилище временно недоступно") from None
    if item.state in {"queued", "processing"}:
        raise HTTPException(409, "Результат ещё не готов")
    if item.state != "completed":
        raise HTTPException(404, "Результат недоступен")
    if download_slots.locked():
        raise HTTPException(429, "Слишком много скачиваний", headers={"Retry-After": "5"})
    await download_slots.acquire()
    try:
        file, size, media_type, filename = background_jobs.artifacts.open_result(job_id)
        try:
            return ResultStream(file, size, media_type, filename)
        except BaseException:
            file.close()
            raise
    except (ArtifactUnavailable, FileNotFoundError, ValueError, OSError):
        download_slots.release()
        raise HTTPException(404, "Результат удалён или недоступен") from None
    except BaseException:
        download_slots.release()
        raise


def new_job(user_id: int) -> str:
    if jobs is None:
        raise HTTPException(status_code=503, detail="Хранилище заданий не запущено")
    try:
        return jobs.create(user_id).job_id
    except JobCapacityExceeded:
        raise HTTPException(status_code=503, detail="Слишком много активных заданий. Повтори позже.", headers={"Retry-After": "15"}) from None


@asynccontextmanager
async def conversion_job(user_id, uploads):
    job_id = None
    acquired = False
    try:
        job_id = new_job(user_id)
        await admission.acquire(slots)
        acquired = True
        jobs.transition(job_id, user_id, "processing")
        yield job_id
    except asyncio.CancelledError:
        if job_id is not None:
            try:
                if jobs.get(job_id, user_id).state in {"queued", "processing"}:
                    jobs.transition(job_id, user_id, "cancelled")
            except (sqlite3.Error, JobNotFound, JobStateError):
                logger.error("Job cancellation metadata update failed")
        raise
    except QueueClosed:
        raise HTTPException(status_code=503, detail="Сервер перезапускается. Повтори запрос позже.", headers={"Retry-After": "10"}) from None
    except QueueFull:
        raise HTTPException(status_code=429, detail="Очередь заполнена. Попробуй повторить позже.", headers={"Retry-After": "15"}) from None
    except QueueTimeout:
        raise HTTPException(status_code=503, detail="Слишком долгое ожидание. Попробуй ещё раз.", headers={"Retry-After": "5"}) from None
    except sqlite3.Error:
        logger.error("Job metadata unavailable")
        raise HTTPException(status_code=503, detail="Хранилище заданий временно недоступно") from None
    finally:
        try:
            if job_id is not None:
                try:
                    if jobs.get(job_id, user_id).state in {"queued", "processing"}:
                        jobs.transition(job_id, user_id, "failed")
                except (sqlite3.Error, JobNotFound, JobStateError):
                    logger.error("Job final metadata update failed")
        finally:
            if acquired:
                slots.release()
            for upload in uploads:
                await upload.close()


@api.get("/api/v1/session")
async def session(user_id: int = Depends(authenticated_user)):
    return {"ok": True, "user_id": user_id, "max_upload_bytes": MAX_INPUT_BYTES}


async def run_managed_worker(payload):
    # Isolated handler tests inject their own registry without app lifespan.
    # Production admission fails closed unless lifespan initialized SQLite.
    if job_manager is None:
        return await run_worker(payload)
    try:
        return await job_manager.run(lambda: run_worker(payload))
    except ManagerFull:
        raise HTTPException(status_code=429, detail="Очередь обработчиков заполнена", headers={"Retry-After": "15"}) from None
    except ManagerClosed:
        raise HTTPException(status_code=503, detail="Обработчики останавливаются", headers={"Retry-After": "10"}) from None
    except TimeoutError:
        raise WorkerTimeout("Обработка заняла слишком много времени") from None


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
    async with conversion_job(user_id, [upload]) as job_id:
        work = None
        try:
            work = Workspace(prefix="fileshape_api_")
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
            result = await run_managed_worker({
                "operation": "single", "work": work.name,
                "suffix": suffix, "action": action, "pages": pages,
            })
            if "info" in result:
                if work is not None:
                    work.cleanup()
                jobs.transition(job_id, user_id, "completed")
                return JSONResponse(result["info"], headers={"Cache-Control": "no-store", "X-FileShape-Job-Id": job_id})

            target = Path(work.name) / result["filename"]
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError("Пустой результат")
            if target.stat().st_size > MAX_RESULT_BYTES:
                raise HTTPException(status_code=413, detail="Результат слишком большой")
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            jobs.transition(job_id, user_id, "completed")
            return FileResponse(
                target,
                filename=target.name,
                media_type=content_type,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-FileShape-Job-Id": job_id},
                background=BackgroundTask(work.cleanup),
            )
        except asyncio.CancelledError:
            # Cancellation does not inherit from Exception. Remove partial uploads
            # and outputs before propagating cancellation to the ASGI server.
            if work is not None:
                work.cleanup()
            raise
        except HTTPException:
            if work is not None:
                work.cleanup()
            raise
        except WorkerTimeout as exc:
            if work is not None:
                work.cleanup()
            raise HTTPException(status_code=504, detail=str(exc)) from None
        except ValueError as exc:
            if work is not None:
                work.cleanup()
            raise HTTPException(status_code=422, detail=str(exc)[:200]) from None
        except Exception:
            if work is not None:
                work.cleanup()
            logger.error("FileShape API processing failed")
            raise HTTPException(status_code=422, detail="Не удалось прочитать или обработать файл") from None


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
    async with conversion_job(user_id, uploads) as job_id:
        work = None
        try:
            work = Workspace(prefix="fileshape_batch_")
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

            await run_managed_worker({
                "operation": "batch", "work": work.name,
                "suffixes": [file_kind(upload.filename or "")[1] for upload in uploads],
            })
            target = Path(work.name) / "fileshape_photos.pdf"
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError("Не удалось создать PDF")
            if target.stat().st_size > MAX_RESULT_BYTES:
                raise HTTPException(status_code=413, detail="Результат слишком большой")
            jobs.transition(job_id, user_id, "completed")
            return FileResponse(
                target,
                filename=target.name,
                media_type="application/pdf",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-FileShape-Job-Id": job_id},
                background=BackgroundTask(work.cleanup),
            )
        except asyncio.CancelledError:
            # Cancellation does not inherit from Exception. Remove partial uploads
            # and outputs before propagating cancellation to the ASGI server.
            if work is not None:
                work.cleanup()
            raise
        except HTTPException:
            if work is not None:
                work.cleanup()
            raise
        except WorkerTimeout as exc:
            if work is not None:
                work.cleanup()
            raise HTTPException(status_code=504, detail=str(exc)) from None
        except ValueError as exc:
            if work is not None:
                work.cleanup()
            raise HTTPException(status_code=422, detail=str(exc)[:200]) from None
        except Exception:
            if work is not None:
                work.cleanup()
            logger.error("Multi-image PDF failed")
            raise HTTPException(status_code=422, detail="Не удалось объединить изображения") from None
