"""Bounded asynchronous single-file conversions; files are private and ephemeral."""
import asyncio
import json
import hashlib
import re
import logging
import mimetypes
import os
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any
import sqlite3

from fastapi import HTTPException

from api.artifacts import ArtifactCapacity, ArtifactUnavailable
from api.architecture_ports import ArtifactStoragePort, DispatchHandlePort, JobDispatchPort, JobMetadataPort
from api.jobs import JobCapacityExceeded, JobNotFound, JobStateError
from api.durable_jobs import IdempotencyConflict, IdempotencyPending
from api.worker_runner import WorkerTimeout
from api.job_manager import ManagerClosed, ManagerFull

logger = logging.getLogger(__name__)
IDEMPOTENCY_KEY = re.compile(r'[A-Za-z0-9_-]{16,128}\Z')
RESULT_NAMES = frozenset({
    'converted.jpg', 'converted.png', 'converted.webp', 'converted.pdf',
    'optimized.webp', 'rotated.pdf', 'result.pdf', 'converted.mp3',
    'converted.ogg', 'converted.wav', 'converted.txt', 'converted.docx',
})


class BackgroundJobs:
    def __init__(
        self,
        store: JobMetadataPort,
        manager: JobDispatchPort,
        artifacts: ArtifactStoragePort,
        worker: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        max_input: int,
        max_result: int,
        *,
        max_requests: int | None = None,
    ):
        if max_requests is None:
            max_requests = manager.capacity + 20
        if type(max_requests) is not int or not 1 <= max_requests <= 1000:
            raise ValueError('Invalid background upload limit')
        self.store = store
        self.manager = manager
        self.artifacts = artifacts
        self.worker = worker
        self.max_input = max_input
        self.max_result = max_result
        self.handles: dict[str, DispatchHandlePort] = {}
        self.owners = {}
        # One reservation follows a newly claimed job through preparation,
        # execution and any deferred metadata update. No accepted job loses
        # reconciliation merely because the bounded retry queue is full.
        self._tracked = set()
        self._preparing = set()
        self._pending_terminal = {}
        self._pending_discard = {}
        self.max_requests = max_requests
        self._requests = set()
        self._closing = False
        self._prepare_stop = None

    @property
    def request_count(self):
        return len(self._requests)

    def _check_open(self):
        if self._closing:
            raise HTTPException(503, 'Сервер останавливается', headers={'Retry-After': '10'})

    async def stop_preparing(self):
        """Cancel uploads/hash/validation requests before artifact ownership ends."""
        self._closing = True
        if asyncio.current_task() in self._requests:
            raise RuntimeError('Cannot stop uploads from an active upload request')
        if self._prepare_stop is None:
            self._prepare_stop = asyncio.create_task(self._drain_requests())
        interrupted = False
        while not self._prepare_stop.done():
            try:
                await asyncio.shield(self._prepare_stop)
            except asyncio.CancelledError:
                interrupted = True
        self._prepare_stop.result()
        if interrupted:
            raise asyncio.CancelledError()

    async def _drain_requests(self):
        requests = tuple(self._requests)
        for task in requests:
            task.cancel()
        if requests:
            await asyncio.gather(*requests, return_exceptions=True)

    @property
    def tracked_count(self):
        return len(self._tracked)

    @property
    def pending_count(self):
        return len(self._pending_terminal) + len(self._pending_discard)

    @property
    def active_ids(self):
        return frozenset(self._preparing) | frozenset(self.handles)

    def _forget(self, job_id):
        self._tracked.discard(job_id)
        self._preparing.discard(job_id)
        self._pending_terminal.pop(job_id, None)
        self._pending_discard.pop(job_id, None)

    def _discard_rejected(self, job_id, owner):
        """Delete only the owned queued claim that never reached a caller."""
        if self.store.discard_queued(job_id, owner):
            self._forget(job_id)
            return True
        try:
            self.store.get(job_id, owner)
        except JobNotFound:
            self._forget(job_id)
            return True
        # A changed state is not permission to finish someone else's work.
        # Keep the known-rejected key blocked until safe deletion/expiry.
        self._pending_discard.pop(job_id, None)
        self._pending_discard[job_id] = owner
        return False

    def _remember_terminal(self, job_id, owner, state):
        if job_id not in self._tracked:
            # Production handles already reserved a slot before upload. This
            # branch also keeps explicit settlement of injected handles safe.
            if len(self._tracked) >= self.store.max_entries:
                logger.error('Background reconciliation capacity exceeded')
                return
            self._tracked.add(job_id)
        self._pending_terminal.setdefault(job_id, (owner, state))

    def reconcile(self, max_updates=50):
        """Retry only known completed handles/rejected admissions, never replay."""
        if type(max_updates) is not int or not 1 <= max_updates <= 1000:
            raise ValueError('Invalid reconciliation limit')
        attempted = 0
        resolved = 0
        for job_id, owner in tuple(self._pending_discard.items()):
            if attempted >= max_updates:
                break
            attempted += 1
            try:
                resolved += self._discard_rejected(job_id, owner)
            except sqlite3.Error:
                # One unavailable connection must not multiply its SQLite busy
                # timeout by the size of the deferred queue.
                logger.error('Background admission reconciliation unavailable')
                return resolved
        for job_id, (owner, state) in tuple(self._pending_terminal.items()):
            if attempted >= max_updates:
                break
            attempted += 1
            try:
                item = self.store.get(job_id, owner)
                if item.state in {'queued', 'processing'}:
                    item = self.store.transition(job_id, owner, state)
            except JobNotFound:
                self._forget(job_id)
                resolved += 1
                try:
                    self.artifacts.discard_unfinished(job_id)
                except (OSError, ArtifactUnavailable):
                    logger.error('Background artifact cleanup failed')
                continue
            except sqlite3.Error:
                logger.error('Background terminal reconciliation unavailable')
                return resolved
            except JobStateError:
                # A concurrent terminal winner is observed on the next pass.
                pending = self._pending_terminal.pop(job_id)
                self._pending_terminal[job_id] = pending
                continue
            self._forget(job_id)
            resolved += 1
            if item.state in {'failed', 'cancelled'}:
                try:
                    self.artifacts.discard(job_id)
                except (OSError, ArtifactUnavailable):
                    logger.error('Background artifact cleanup failed')
        return resolved

    async def _fingerprint(self, upload, action, suffix, pages, retry_of):
        canonical = json.dumps({
            'action': action, 'suffix': suffix, 'pages': pages, 'retry_of': retry_of,
        }, sort_keys=True, separators=(',', ':')).encode('utf-8')
        digest = hashlib.sha256(b'fileshape-job-v1\0' + canonical + b'\0')
        size = 0
        async with asyncio.timeout(30):
            await upload.seek(0)
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > self.max_input:
                    raise HTTPException(413, 'Максимальный размер файла — 20 МБ')
                digest.update(chunk)
            await upload.seek(0)
        if not size:
            raise HTTPException(422, 'Пустой файл')
        return digest.hexdigest()

    async def create(self, upload, action, suffix, pages, owner, *, idempotency_key=None, retry_of=None, metered=False):
        if type(metered) is not bool:
            raise ValueError('Invalid metered setting')
        job = None
        created_new = False
        accepted = False
        request = asyncio.current_task()
        registered = False
        try:
            self._check_open()
            if len(self._requests) >= self.max_requests:
                raise HTTPException(429, 'Слишком много одновременных загрузок', headers={'Retry-After': '5'})
            if request is None or request in self._requests:
                raise RuntimeError('Background uploads require distinct request tasks')
            self._requests.add(request)
            registered = True
            key_hash = None
            if idempotency_key is not None:
                if not isinstance(idempotency_key, str) or IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
                    raise HTTPException(422, 'Некорректный ключ повторного запроса')
                key_hash = hashlib.sha256(idempotency_key.encode('ascii')).hexdigest()
                fingerprint = await self._fingerprint(upload, action, suffix, pages, retry_of)
                self._check_open()
                job, created_new = self.store.create_idempotent(
                    owner, key_hash, fingerprint,
                    allow_create=len(self._tracked) < self.store.max_entries,
                    **({'metered': True} if metered else {}),
                )
                if not created_new:
                    if job.job_id in self._pending_discard:
                        raise HTTPException(503, 'Неудавшийся запрос ещё очищается. Повтори позже.', headers={'Retry-After': '1'})
                    return job
            else:
                if len(self._tracked) >= self.store.max_entries:
                    raise JobCapacityExceeded()
                job = self.store.create(owner, metered=metered) if metered else self.store.create(owner)
                created_new = True
            # Claim and tracking reservation are synchronous on the API loop.
            # Existing accepted replays need no additional tracking slot.
            self._tracked.add(job.job_id)
            self._preparing.add(job.job_id)
            # Include the runner's 50 MiB file cap, not just accepted result size.
            artifact = self.artifacts.reserve(job.job_id, self.max_input + 50 * 1024**2 + 65536)
            source = artifact.path / ('source' + suffix)
            size = 0
            async with asyncio.timeout(30):
                with os.fdopen(os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
                    while chunk := await upload.read(65536):
                        size += len(chunk)
                        if size > self.max_input:
                            raise HTTPException(413, 'Максимальный размер файла — 20 МБ')
                        output.write(chunk)
            if not size:
                raise HTTPException(422, 'Пустой файл')
            self._check_open()
            # Content identification/parsers stay in the resource-limited process.
            await asyncio.wait_for(self.manager.run(lambda: self.worker({
                'operation': 'validate_only', 'work': str(artifact.path), 'suffix': suffix,
            })), timeout=90)
            self._check_open()
            if key_hash is not None:
                # No await between durable acceptance and bounded submission.
                # Submission failure still discards the queued claim below.
                self.store.accept_admission(job.job_id, owner, key_hash)
            handle = self.manager.submit(lambda: self._execute(job.job_id, owner, artifact.path, action, suffix, pages))
            self.handles[job.job_id] = handle
            self.owners[job.job_id] = owner
            self._preparing.discard(job.job_id)
            handle.finished.add_done_callback(lambda _: self._settled(job.job_id, owner, handle))
            accepted = True
            return job
        except IdempotencyPending:
            raise HTTPException(409, 'Такой запрос ещё проверяется. Повтори позже.', headers={'Retry-After': '1'}) from None
        except IdempotencyConflict:
            raise HTTPException(409, 'Ключ запроса уже использован для другой операции') from None
        except (ArtifactCapacity, JobCapacityExceeded):
            raise HTTPException(503, 'Недостаточно места для нового задания', headers={'Retry-After': '30'}) from None
        except ManagerFull:
            raise HTTPException(429, 'Очередь заполнена. Попробуй позже.', headers={'Retry-After': '15'}) from None
        except ManagerClosed:
            raise HTTPException(503, 'Сервер останавливается', headers={'Retry-After': '10'}) from None
        except (TimeoutError, WorkerTimeout):
            raise HTTPException(504, 'Превышено время загрузки или проверки файла') from None
        except ValueError:
            raise HTTPException(422, 'Файл не прошёл проверку') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'Хранилище временно недоступно') from None
        finally:
            try:
                if job is not None and created_new and not accepted:
                    self._preparing.discard(job.job_id)
                    self._pending_discard[job.job_id] = owner
                    try:
                        self._discard_rejected(job.job_id, owner)
                    except sqlite3.Error:
                        logger.error('Background rejected admission cleanup deferred')
                    try:
                        self.artifacts.discard(job.job_id)
                    except OSError:
                        # Reservation stays charged; maintenance retries removal.
                        logger.error('Background artifact cleanup failed')
            finally:
                try:
                    await upload.close()
                finally:
                    if registered:
                        self._requests.discard(request)

    async def cancel(self, job_id, owner):
        # Owner lookup precedes handle access, including for terminal no-ops.
        item = self.store.get(job_id, owner)
        if item.state in {'completed', 'failed', 'cancelled'}:
            return item
        handle = self.handles.get(job_id)
        if handle is None:
            raise HTTPException(503, 'Управление заданием временно недоступно')
        try:
            await handle.cancel()
        finally:
            # Future callbacks can be scheduled for the next event-loop tick.
            # Explicitly settle after cleanup before returning an owned status.
            if handle.done:
                self._settled(job_id, owner, handle)
        return self.store.get(job_id, owner)

    async def retry(self, job_id, upload, action, suffix, pages, owner, *, idempotency_key, metered=False):
        try:
            item = self.store.get(job_id, owner)
            if item.state not in {'failed', 'cancelled'}:
                raise HTTPException(409, 'Повтор доступен только для отменённого или завершившегося ошибкой задания')
            if idempotency_key is None:
                raise HTTPException(422, 'Для повтора необходим ключ запроса')
            return await self.create(upload, action, suffix, pages, owner,
                                     idempotency_key=idempotency_key, retry_of=job_id,
                                     metered=metered)
        finally:
            await upload.close()

    async def _execute(self, job_id, owner, work, action, suffix, pages):
        completed = False
        try:
            self.store.transition(job_id, owner, 'processing')
            result = await self.worker({
                'operation': 'single', 'work': str(work), 'suffix': suffix,
                'action': action, 'pages': pages,
            })
            if 'info' in result:
                data = json.dumps(result['info'], ensure_ascii=False).encode('utf-8')
                if len(data) > 65536:
                    raise ValueError('Result too large')
                filename = 'result.json'
                target = work / filename
                with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as output:
                    output.write(data)
                content_type = 'application/json'
            else:
                filename = result['filename']
                if filename not in RESULT_NAMES:
                    raise ValueError('Unexpected result path')
                target = work / filename
                # ArtifactStore verifies the final inode with O_NOFOLLOW/fstat.
                if target.is_symlink() or not target.is_file() or not 0 < target.stat().st_size <= self.max_result:
                    raise ValueError('Invalid result')
                os.chmod(target, 0o600, follow_symlinks=False)
                content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            (work / ('source' + suffix)).unlink()
            self.artifacts.complete(job_id, filename, content_type)
            self.store.transition(job_id, owner, 'completed')
            completed = True
        finally:
            # Consumer signals finished only after the subprocess and this
            # cleanup complete. The callback then records failed/cancelled.
            if not completed:
                self.artifacts.discard(job_id)

    def _terminal(self, job_id, owner, state):
        try:
            item = self.store.get(job_id, owner)
            if item.state in {'queued', 'processing'}:
                return self.store.transition(job_id, owner, state)
            return item
        except (sqlite3.Error, JobNotFound, JobStateError):
            logger.error('Background job metadata update failed')
            return None

    def _settled(self, job_id, owner, handle):
        if self.handles.get(job_id) is not handle:
            return
        self.handles.pop(job_id)
        self.owners.pop(job_id, None)
        try:
            state = None
            if handle.result.cancelled():
                state = 'cancelled'
            elif handle.result.exception() is not None:
                state = 'failed'
                logger.error('Background conversion failed')
            if state is not None:
                item = self._terminal(job_id, owner, state)
                if item is None:
                    self._remember_terminal(job_id, owner, state)
                else:
                    self._forget(job_id)
                # A completion can win before the manager's result notification.
                # Do not remove a valid completed result in that cancellation race.
                if item is not None and item.state in {'failed', 'cancelled'}:
                    self.artifacts.discard(job_id)
                elif item is None:
                    # Queued cancellation can precede execution entirely. A
                    # SQLite outage must not retain that input indefinitely.
                    # Preserve only results with a known finite artifact TTL.
                    self.artifacts.discard_unfinished(job_id)
            else:
                self._forget(job_id)
        except (OSError, ArtifactUnavailable):
            logger.error('Background artifact cleanup failed')

    def close(self):
        self._closing = True
        if self._requests:
            raise RuntimeError('Background upload requests still active')
        # Caller first stops/joins manager; callbacks may be queued this tick.
        for job_id, handle in tuple(self.handles.items()):
            if not handle.done:
                raise RuntimeError('Background workers still active')
            self._settled(job_id, self.owners[job_id], handle)
        self.reconcile()
        self.artifacts.close()
        self.handles.clear()
        self.owners.clear()
        self._tracked.clear()
        self._preparing.clear()
        self._pending_terminal.clear()
        self._pending_discard.clear()
