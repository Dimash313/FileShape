"""Authenticated, short-lived file transformations for the FileShape Mini App.

Run one API worker behind an HTTPS reverse proxy. Background results are temporary and are not recovered after restart.
"""
import asyncio
import hashlib
import json
import re
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
from aiogram import Bot
from datetime import datetime, timezone

from api.access_policy import AccessDecision, RequiredChannel
from api.telegram_membership import verify_memberships
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from api.artifacts import ArtifactStore, ArtifactUnavailable
from api.conversion_catalog import IMAGE_EXTENSIONS, SUPPORTED, file_kind
from api.background_jobs import BackgroundJobs
from api.admission import AdmissionQueue, QueueClosed, QueueFull, QueueTimeout
from api.auth import InvalidInitData, verify_init_data
from api.ingress import UploadIngressGuard
from api.internal_access import ReplayGuard
from api.campaign_bridge import JoinReplayGuard
from api.campaign_owner import make_campaign_router
from api.campaign_revocations import dispatch_campaign_revocations
from api.jobs import JobCapacityExceeded, JobNotFound, JobStateError, JobRegistry
from api.job_runtime import JobRuntime
from api.durable_jobs import DurableJobStore
from api.usage_ledger import OperationQuotaExceeded, OperationConcurrencyExceeded
from api.job_manager import JobManager, ManagerClosed, ManagerFull
from api.observability import RequestTrace
from api.readiness import readiness_status
from api.worker_runner import WorkerFailed, WorkerTimeout, run_worker
from api.workspaces import Workspace, OrphanCleaner, cleanup_orphans
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
orphan_cleaner = None
shutdown_task = None
download_slots = asyncio.Semaphore(4)
limiter_lock = asyncio.Lock()
recent_requests: dict[int, deque[float]] = defaultdict(deque)
recent_membership_checks: dict[int, deque[float]] = defaultdict(deque)
internal_access_replay = ReplayGuard()
internal_bot_operation_replay = ReplayGuard()
join_replay = JoinReplayGuard()


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


async def authorize_new_processing(user_id: int = Depends(authenticated_user)) -> int:
    """Only new admissions are gated. Status, cancellation and results stay owner-scoped."""
    if jobs is None:
        raise HTTPException(status_code=503, detail="Хранилище заданий не запущено")
    if job_runtime is None and not hasattr(jobs, "premium_expiry"):
        # Legacy in-memory test harness; production always starts JobRuntime.
        return user_id
    try:
        now = datetime.now(timezone.utc)
        expiry = jobs.premium_expiry(user_id)
        channels = tuple(
            RequiredChannel(
                chat_id=chat_id,
                starts_at=datetime.fromtimestamp(start, timezone.utc),
                ends_at=None if end is None else datetime.fromtimestamp(end, timezone.utc),
                enabled=enabled,
            )
            for chat_id, start, end, enabled in jobs.list_required_channels()
        )
        if expiry is not None and expiry > now.timestamp():
            return user_id
        if not any(channel.active_at(now) for channel in channels):
            return user_id
    except (sqlite3.Error, ValueError, OverflowError, OSError):
        logger.error("Access configuration unavailable")
        raise HTTPException(status_code=503, detail="Проверка доступа временно недоступна") from None
    # Separate verification budget protects Telegram API without changing the
    # existing per-operation quota and validation order.
    await enforce_rate_limit(user_id, membership=True)
    try:
        bot = Bot(token=get_settings().bot_token)
    except (RuntimeError, ValueError, TypeError):
        logger.error("Telegram membership verifier initialization failed")
        raise HTTPException(status_code=503, detail="Проверка доступа временно недоступна") from None
    try:
        try:
            decision = await verify_memberships(
                bot, user_id=user_id, channels=channels, now=now,
            )
        except (ValueError, TypeError, OSError):
            logger.error("Telegram membership policy configuration unavailable")
            raise HTTPException(status_code=503, detail="Проверка доступа временно недоступна") from None
    finally:
        await bot.session.close()
    if decision is AccessDecision.SUBSCRIPTION_REQUIRED:
        raise HTTPException(status_code=403, detail="Подпишись на обязательные каналы")
    if decision is not AccessDecision.ALLOWED:
        raise HTTPException(status_code=503, detail="Не удалось проверить подписку. Повтори позже")
    return user_id


async def enforce_rate_limit(user_id: int, *, membership: bool = False) -> None:
    now = time.monotonic()
    async with limiter_lock:
        cache = recent_membership_checks if membership else recent_requests
        window = cache[user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Слишком много запросов. Повтори позже.")
        window.append(now)
        # Prevent unused per-user queues from accumulating forever.
        if len(cache) > 10_000:
            for key in list(cache):
                if not cache[key] or now - cache[key][-1] > 120:
                    del cache[key]


async def maintain_metadata(store):
    while True:
        await asyncio.sleep(60)
        # A database outage must not prevent expiry or orphan cleanup.
        operations = []
        if background_jobs is not None:
            operations.extend((background_jobs.reconcile, background_jobs.artifacts.reconcile))
        if hasattr(store, "expire_bot_operations"):
            operations.append(store.expire_bot_operations)
        operations.append(store.prune_terminal)
        if hasattr(store, "expire_campaigns"):
            operations.append(store.expire_campaigns)
        for operation in operations:
            try:
                operation()
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                logger.error("Job maintenance operation failed")
        if hasattr(store, "pending_campaign_revocations"):
            try:
                await dispatch_campaign_revocations(store)
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                logger.error("Campaign revocation reconciliation unavailable")
        try:
            await asyncio.to_thread(orphan_cleaner.sweep if orphan_cleaner is not None else cleanup_orphans)
        except (OSError, ValueError, RuntimeError):
            logger.error("Workspace cleanup failed")


@api.on_event("shutdown")
async def stop_accepting_conversions():
    global shutdown_task
    admission.close()
    if shutdown_task is None:
        shutdown_task = asyncio.create_task(close_runtime_resources())
    interrupted = False
    while not shutdown_task.done():
        try:
            await asyncio.shield(shutdown_task)
        except asyncio.CancelledError:
            interrupted = True
    shutdown_task.result()
    if interrupted:
        raise asyncio.CancelledError()


async def close_runtime_resources():
    """Retain instance/artifact ownership until every writer has stopped."""
    global job_runtime, metadata_maintenance, jobs, job_manager, background_jobs, orphan_cleaner
    if background_jobs is not None:
        await background_jobs.stop_preparing()
    if job_manager is not None:
        await job_manager.close()
        job_manager = None
    try:
        if background_jobs is not None:
            background_jobs.close()
    finally:
        background_jobs = None
        try:
            if metadata_maintenance is not None:
                metadata_maintenance.cancel()
                await asyncio.gather(metadata_maintenance, return_exceptions=True)
                metadata_maintenance = None
        finally:
            try:
                if orphan_cleaner is not None:
                    try:
                        await asyncio.to_thread(orphan_cleaner.close)
                    finally:
                        orphan_cleaner = None
            finally:
                try:
                    if job_runtime is not None:
                        try:
                            job_runtime.close()
                        finally:
                            job_runtime = None
                finally:
                    jobs = None


@api.on_event("startup")
async def remove_abandoned_workspaces():
    global admission, jobs, job_runtime, metadata_maintenance, job_manager, background_jobs, orphan_cleaner, shutdown_task
    if job_runtime is not None:
        raise RuntimeError("API lifecycle already started")
    shutdown_task = None
    runtime = JobRuntime(os.environ.get("FILESHAPE_STATE_DIR", "./state"))
    cleaner = OrphanCleaner()
    artifacts = None
    manager = None
    try:
        await asyncio.to_thread(cleaner.sweep)
        artifacts = ArtifactStore()
        manager = JobManager(MAX_CONCURRENT_JOBS, max_pending=20)
        service = BackgroundJobs(runtime.store, manager, artifacts, lambda payload: run_worker(payload), MAX_INPUT_BYTES, MAX_RESULT_BYTES)
    except BaseException:
        try:
            try:
                if manager is not None:
                    await manager.close()
            finally:
                if artifacts is not None:
                    artifacts.close()
        finally:
            try:
                await asyncio.to_thread(cleaner.close)
            finally:
                runtime.close()
        raise
    if admission.closing:
        admission = AdmissionQueue(max_waiters=20, wait_seconds=90.0)
    job_manager = manager
    job_runtime = runtime
    jobs = runtime.store
    orphan_cleaner = cleaner
    background_jobs = service
    metadata_maintenance = asyncio.create_task(maintain_metadata(jobs))


@api.post("/internal/v1/access/check")
async def internal_access_check(
    user: str = Header(default="", alias="X-FileShape-User"),
    timestamp: str = Header(default="", alias="X-FileShape-Time"),
    nonce: str = Header(default="", alias="X-FileShape-Nonce"),
    signature: str = Header(default="", alias="X-FileShape-Signature"),
):
    """Authenticated bot service only. Never accept client-supplied membership."""
    if job_runtime is None or jobs is None:
        raise HTTPException(status_code=503, detail="Access service unavailable")
    try:
        secret = get_settings().bot_token
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Access service unavailable") from None
    try:
        user_id = internal_access_replay.verify(
            token=secret, user=user, timestamp=timestamp,
            nonce=nonce, signature=signature,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    try:
        await authorize_new_processing(user_id)
    except HTTPException as error:
        decision = (
            AccessDecision.SUBSCRIPTION_REQUIRED
            if error.status_code == 403
            else AccessDecision.VERIFICATION_UNAVAILABLE
        )
    else:
        decision = AccessDecision.ALLOWED
    return JSONResponse({"decision": decision.value}, headers={"Cache-Control": "no-store"})


_BOT_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_BOT_JOB_RE = re.compile(r"[A-Za-z0-9_-]{16,100}\Z")


async def _read_bot_operation_body(request: Request, *, allowed_keys: set[str]) -> dict:
    """Bound internal JSON without trusting Content-Length or unbounded request.body."""
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 512:
            raise HTTPException(status_code=413, detail="Request too large")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Invalid request") from None
    if not isinstance(value, dict) or set(value) != allowed_keys:
        raise HTTPException(status_code=422, detail="Invalid operation fields")
    return value


def _verify_bot_operation(user: str, timestamp: str, nonce: str,
                          signature: str, *, scope: str) -> int:
    if job_runtime is None or jobs is None:
        raise HTTPException(status_code=503, detail="Operation service unavailable")
    try:
        return internal_bot_operation_replay.verify(
            token=get_settings().bot_token, user=user, timestamp=timestamp,
            nonce=nonce, signature=signature, scope=scope,
        )
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=401, detail="Unauthorized") from None


@api.post("/internal/v1/operations/usage")
async def internal_bot_usage(
    request: Request,
    user: str = Header(default="", alias="X-FileShape-User"),
    timestamp: str = Header(default="", alias="X-FileShape-Time"),
    nonce: str = Header(default="", alias="X-FileShape-Nonce"),
    signature: str = Header(default="", alias="X-FileShape-Signature"),
):
    """Read-only, owner-scoped bot profile via a signed and replay-guarded assertion."""
    await _read_bot_operation_body(request, allowed_keys=set())
    user_id = _verify_bot_operation(
        user, timestamp, nonce, signature, scope="usage"
    )
    await enforce_rate_limit(user_id)
    return _usage_response(user_id)


@api.post("/internal/v1/operations/reserve")
async def internal_bot_reserve_operation(
    request: Request,
    user: str = Header(default="", alias="X-FileShape-User"),
    timestamp: str = Header(default="", alias="X-FileShape-Time"),
    nonce: str = Header(default="", alias="X-FileShape-Nonce"),
    signature: str = Header(default="", alias="X-FileShape-Signature"),
):
    data = await _read_bot_operation_body(request, allowed_keys={"request_id"})
    request_id = data["request_id"]
    if not isinstance(request_id, str) or _BOT_ID_RE.fullmatch(request_id) is None:
        raise HTTPException(status_code=422, detail="Invalid operation identifier")
    user_id = _verify_bot_operation(
        user, timestamp, nonce, signature, scope="reserve:" + request_id
    )
    await authorize_new_processing(user_id)
    # Prevent repeated invalid bot uploads from bypassing HTTP rate controls.
    await enforce_rate_limit(user_id)
    digest = hashlib.sha256(b"fileshape-bot-operation-v1\0" + request_id.encode("ascii")).hexdigest()
    try:
        item, created = jobs.reserve_bot_operation(user_id, digest)
    except (OperationQuotaExceeded, OperationConcurrencyExceeded) as exc:
        raise quota_error(exc) from None
    except JobCapacityExceeded:
        raise HTTPException(status_code=503, detail="Processing capacity unavailable") from None
    except (sqlite3.Error, OSError):
        raise HTTPException(status_code=503, detail="Operation store unavailable") from None
    return JSONResponse(
        {"job_id": item.job_id, "created": created, "state": item.state},
        headers={"Cache-Control": "no-store"},
    )


@api.post("/internal/v1/operations/settle")
async def internal_bot_settle_operation(
    request: Request,
    user: str = Header(default="", alias="X-FileShape-User"),
    timestamp: str = Header(default="", alias="X-FileShape-Time"),
    nonce: str = Header(default="", alias="X-FileShape-Nonce"),
    signature: str = Header(default="", alias="X-FileShape-Signature"),
):
    data = await _read_bot_operation_body(request, allowed_keys={"job_id", "success"})
    job_id, success = data["job_id"], data["success"]
    if (not isinstance(job_id, str) or _BOT_JOB_RE.fullmatch(job_id) is None
            or type(success) is not bool):
        raise HTTPException(status_code=422, detail="Invalid settlement")
    user_id = _verify_bot_operation(
        user, timestamp, nonce, signature,
        scope="settle:" + job_id + (":1" if success else ":0"),
    )
    try:
        item = jobs.settle_bot_operation(user_id, job_id, success=success)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="Operation not found") from None
    except JobStateError:
        raise HTTPException(status_code=409, detail="Operation state conflict") from None
    except (sqlite3.Error, OSError):
        raise HTTPException(status_code=503, detail="Operation store unavailable") from None
    return JSONResponse(
        {"job_id": item.job_id, "state": item.state},
        headers={"Cache-Control": "no-store"},
    )


@api.post("/internal/v1/campaigns/join")
async def internal_campaign_join(
    request: Request,
    timestamp: str = Header(default="", alias="X-FileShape-Time"),
    nonce: str = Header(default="", alias="X-FileShape-Nonce"),
    signature: str = Header(default="", alias="X-FileShape-Signature"),
):
    """Bot-only join event ingestion; no public or user-supplied campaign IDs."""
    if job_runtime is None or jobs is None:
        raise HTTPException(status_code=503, detail="Campaign service unavailable")
    # Bound JSON before parsing; never accept multipart or large payloads.
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON required")
    # Stream with a hard cap: never buffer an untrusted large request body.
    parts = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > 1024:
            raise HTTPException(status_code=413, detail="Payload too large")
        parts.append(chunk)
    body = b"".join(parts)
    try:
        import json
        payload = json.loads(body)
        token = get_settings().bot_token
        join_replay.verify(token, payload, timestamp, nonce, signature)
    except (ValueError, TypeError, RuntimeError, UnicodeError):
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    try:
        recorded = jobs.record_attributed_join(**payload)
    except (sqlite3.Error, OSError):
        logger.error("Campaign join storage unavailable")
        raise HTTPException(status_code=503, detail="Campaign storage unavailable") from None
    if recorded and hasattr(jobs, "pending_campaign_revocations"):
        # Never roll back a verified join because Telegram revocation is down.
        try:
            await dispatch_campaign_revocations(jobs, limit=5)
        except (sqlite3.Error, OSError, ValueError, RuntimeError):
            logger.error("Campaign revocation deferred to maintenance")
    return JSONResponse({"recorded": recorded}, headers={"Cache-Control": "no-store"})


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/ready")
async def ready():
    result = await asyncio.to_thread(readiness_status)
    result["checks"]["job_metadata"] = job_runtime is not None
    try:
        result["checks"]["artifact_storage"] = background_jobs is not None and background_jobs.artifacts.has_disk_margin()
    except OSError:
        result["checks"]["artifact_storage"] = False
    if not result["checks"]["artifact_storage"]:
        result["status"] = "unavailable"
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
    pages: str = Form(default=""), user_id: int = Depends(authorize_new_processing),
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
        try:
            item = await background_jobs.create(upload, action, suffix, pages, user_id,
                                                idempotency_key=idempotency_key, metered=True)
        except (OperationQuotaExceeded, OperationConcurrencyExceeded) as exc:
            raise quota_error(exc) from None
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
    pages: str = Form(default=""), user_id: int = Depends(authorize_new_processing),
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
                                               idempotency_key=idempotency_key, metered=True)
        except JobNotFound:
            raise HTTPException(404, "Задание не найдено") from None
        except (OperationQuotaExceeded, OperationConcurrencyExceeded) as exc:
            raise quota_error(exc) from None
        except sqlite3.Error:
            raise HTTPException(503, "Хранилище временно недоступно") from None
        return JSONResponse(item.public(), status_code=202, headers={
            "Cache-Control": "no-store", "Location": f"/api/v1/jobs/{item.job_id}",
        })
    finally:
        await upload.close()


class BoundedFileResponse(FileResponse):
    """Compatibility downloads must release workspaces on disconnect/deadline."""
    timeout_seconds = 120

    async def __call__(self, scope, receive, send):
        cleanup, self.background = self.background, None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                await super().__call__(scope, receive, send)
        finally:
            if cleanup is not None:
                await cleanup()


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


def quota_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OperationConcurrencyExceeded):
        return HTTPException(status_code=429,
                             detail="Дождись завершения текущей операции",
                             headers={"Retry-After": "5"})
    return HTTPException(status_code=429,
                         detail="Лимит операций исчерпан. Следующий сброс — в 00:00 UTC.")


def new_job(user_id: int) -> str:
    if jobs is None:
        raise HTTPException(status_code=503, detail="Хранилище заданий не запущено")
    try:
        # Legacy in-memory test harness cannot persist quota reservations.
        # Production startup always installs a durable store with JobRuntime.
        if job_runtime is None and isinstance(jobs, JobRegistry):
            return jobs.create(user_id).job_id
        return jobs.create(user_id, metered=True).job_id
    except JobCapacityExceeded:
        raise HTTPException(status_code=503, detail="Слишком много активных заданий. Повтори позже.", headers={"Retry-After": "15"}) from None
    except (OperationQuotaExceeded, OperationConcurrencyExceeded) as exc:
        raise quota_error(exc) from None


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


def _usage_response(user_id: int) -> JSONResponse:
    if jobs is None or not hasattr(jobs, "usage_snapshot"):
        raise HTTPException(status_code=503, detail="Учёт операций временно недоступен")
    try:
        snapshot = jobs.usage_snapshot(user_id)
    except (sqlite3.Error, ValueError, OverflowError, OSError):
        logger.error("Usage snapshot unavailable")
        raise HTTPException(status_code=503, detail="Учёт операций временно недоступен") from None
    return JSONResponse({
        **snapshot,
        "enforced": job_runtime is not None and isinstance(jobs, DurableJobStore),
        "purchases_enabled": False,
    }, headers={"Cache-Control": "no-store"})


@api.get("/api/v1/usage")
async def usage_status(user_id: int = Depends(authenticated_user)):
    """Owner-scoped persisted allowances from the processing quota ledger."""
    await enforce_rate_limit(user_id)
    return _usage_response(user_id)


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
    user_id: int = Depends(authorize_new_processing),
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
            return BoundedFileResponse(
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
    user_id: int = Depends(authorize_new_processing),
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
            return BoundedFileResponse(
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


# Owner-only campaign endpoints share the API-owned durable SQLite store.
api.include_router(make_campaign_router(authenticated_user, lambda: jobs if job_runtime is not None else None))
