"""Bounded asynchronous single-file conversions; files are private and ephemeral."""
import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path
import sqlite3

from fastapi import HTTPException

from api.artifacts import ArtifactCapacity, ArtifactUnavailable
from api.jobs import JobCapacityExceeded, JobNotFound, JobStateError
from api.worker_runner import WorkerTimeout
from api.job_manager import ManagerClosed, ManagerFull

logger = logging.getLogger(__name__)
RESULT_NAMES = frozenset({
    'converted.jpg', 'converted.png', 'converted.webp', 'converted.pdf',
    'optimized.webp', 'rotated.pdf', 'result.pdf', 'converted.mp3',
    'converted.ogg', 'converted.wav', 'converted.txt', 'converted.docx',
})


class BackgroundJobs:
    def __init__(self, store, manager, artifacts, worker, max_input, max_result):
        self.store = store
        self.manager = manager
        self.artifacts = artifacts
        self.worker = worker
        self.max_input = max_input
        self.max_result = max_result
        self.handles = {}
        self.owners = {}

    async def create(self, upload, action, suffix, pages, owner):
        job = None
        accepted = False
        cancelled = False
        try:
            job = self.store.create(owner)
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
            # Content identification/parsers stay in the resource-limited process.
            await asyncio.wait_for(self.manager.run(lambda: self.worker({
                'operation': 'validate_only', 'work': str(artifact.path), 'suffix': suffix,
            })), timeout=90)
            handle = self.manager.submit(lambda: self._execute(job.job_id, owner, artifact.path, action, suffix, pages))
            self.handles[job.job_id] = handle
            self.owners[job.job_id] = owner
            handle.finished.add_done_callback(lambda _: self._settled(job.job_id, owner, handle))
            accepted = True
            return job
        except asyncio.CancelledError:
            cancelled = True
            raise
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
                if job is not None and not accepted:
                    try:
                        self.store.discard_queued(job.job_id, owner)
                    except sqlite3.Error:
                        self._terminal(job.job_id, owner, 'cancelled' if cancelled else 'failed')
                    try:
                        self.artifacts.discard(job.job_id)
                    except OSError:
                        # Reservation stays charged; maintenance retries removal.
                        logger.error('Background artifact cleanup failed')
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
            if self.store.get(job_id, owner).state in {'queued', 'processing'}:
                self.store.transition(job_id, owner, state)
        except (sqlite3.Error, JobNotFound, JobStateError):
            logger.error('Background job metadata update failed')

    def _settled(self, job_id, owner, handle):
        if self.handles.pop(job_id, None) is None:
            return
        self.owners.pop(job_id, None)
        try:
            if handle.result.cancelled():
                self._terminal(job_id, owner, 'cancelled')
                self.artifacts.discard(job_id)
            elif handle.result.exception() is not None:
                self._terminal(job_id, owner, 'failed')
                self.artifacts.discard(job_id)
                logger.error('Background conversion failed')
        except (OSError, ArtifactUnavailable):
            logger.error('Background artifact cleanup failed')

    def close(self):
        # Caller first stops/joins manager; callbacks may be queued this tick.
        for job_id, handle in tuple(self.handles.items()):
            if not handle.done:
                raise RuntimeError('Background workers still active')
            self._settled(job_id, self.owners[job_id], handle)
        self.artifacts.close()
        self.handles.clear()
