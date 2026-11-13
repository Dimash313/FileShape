"""Actual process death must release locks without replaying private input files."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import server
from api.job_runtime import JobRuntime
from api.jobs import JobNotFound
from api.workspaces import cleanup_orphans
from test_api import signed_init_data, TOKEN


CHILD_RUNTIME = r'''
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

from api.artifacts import ArtifactStore
from api.job_runtime import JobRuntime

state, artifacts_parent, ready = map(Path, sys.argv[1:])
runtime = JobRuntime(state)
artifacts = ArtifactStore(artifacts_parent)
store = runtime.store
owner = 11
jobs = {}
for label in ('queued', 'processing', 'completed', 'pending'):
    key_hash = hashlib.sha256(('fixture-key-' + label).encode()).hexdigest()
    fingerprint = hashlib.sha256(('fixture-input-' + label).encode()).hexdigest()
    job, is_new = store.create_idempotent(owner, key_hash, fingerprint)
    assert is_new
    if label != 'pending':
        store.accept_admission(job.job_id, owner, key_hash)
    if label in ('processing', 'completed'):
        store.transition(job.job_id, owner, 'processing')
    item = artifacts.reserve(job.job_id, 4096)
    filename = 'result.txt' if label == 'completed' else 'source.txt'
    with os.fdopen(os.open(item.path / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
        output.write(('fixture-' + label).encode())
    if label == 'completed':
        artifacts.complete(job.job_id, filename, 'text/plain')
        store.transition(job.job_id, owner, 'completed')
    jobs[label] = {'id': job.job_id, 'path': str(item.path), 'file': filename}
ready.write_text(json.dumps({'root': str(artifacts.path), 'jobs': jobs}))
while True:
    signal.pause()
'''


@unittest.skipUnless(os.name == 'posix' and hasattr(signal, 'SIGKILL'), 'Requires POSIX process locks and SIGKILL')
class ProcessCrashRecoveryTests(unittest.TestCase):
    def test_sigkill_releases_locks_reconciles_metadata_and_removes_only_orphan_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state'
            artifacts_parent = root / 'workspaces'
            ready = root / 'ready.json'
            child = subprocess.Popen(
                [sys.executable, '-c', CHILD_RUNTIME, str(state), str(artifacts_parent), str(ready)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 8
                while not ready.is_file():
                    if child.poll() is not None:
                        self.fail('Fixture child failed: ' + child.stderr.read().decode('utf-8', errors='replace')[-1000:])
                    if time.monotonic() >= deadline:
                        self.fail('Fixture child did not become ready within eight seconds')
                    time.sleep(0.02)
                fixture = json.loads(ready.read_text())
                artifact_root = Path(fixture['root'])
                jobs = fixture['jobs']
                # A logical age jump makes every fixture eligible by age, but
                # another process still holds the artifact and SQLite locks.
                logical_now = time.time() + 7200
                with patch('api.workspaces.workspace_root', return_value=artifacts_parent):
                    self.assertEqual(cleanup_orphans(now=logical_now), 0)
                self.assertTrue(artifact_root.is_dir())
                for label, job in jobs.items():
                    self.assertEqual((Path(job['path']) / job['file']).read_bytes(), ('fixture-' + label).encode())
                with self.assertRaisesRegex(RuntimeError, 'Another API process'):
                    JobRuntime(state)

                child.kill()
                self.assertEqual(child.wait(timeout=5), -signal.SIGKILL)
                self.assertTrue(artifact_root.is_dir(), 'SIGKILL must bypass ordinary in-process cleanup')
                with_runtime = JobRuntime(state)
                try:
                    store = with_runtime.store
                    self.assertEqual(store.get(jobs['queued']['id'], 11).state, 'failed')
                    self.assertEqual(store.get(jobs['processing']['id'], 11).state, 'failed')
                    self.assertEqual(store.get(jobs['completed']['id'], 11).state, 'completed')
                    with self.assertRaises(JobNotFound):
                        store.get(jobs['pending']['id'], 11)
                    self.assertEqual(store._db.execute('SELECT count(*) FROM admissions WHERE accepted=0').fetchone()[0], 0)
                    self.assertEqual(store._db.execute('SELECT count(*) FROM jobs').fetchone()[0], 3)
                    # Metadata recovery never executes, replaces or replays input.
                    self.assertTrue(artifact_root.is_dir())
                    self.assertEqual((Path(jobs['processing']['path']) / 'source.txt').read_bytes(), b'fixture-processing')
                    with patch('api.workspaces.workspace_root', return_value=artifacts_parent):
                        self.assertEqual(cleanup_orphans(now=logical_now), 1)
                        self.assertEqual(cleanup_orphans(now=logical_now), 0)
                    self.assertFalse(artifact_root.exists())
                    self.assertEqual(store.get(jobs['completed']['id'], 11).state, 'completed')
                finally:
                    with_runtime.close()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stderr.close()


@unittest.skipUnless(os.name == 'posix' and hasattr(signal, 'SIGKILL'), 'Requires POSIX worker process groups')
class UnexpectedWorkerDeathTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {
            'BOT_TOKEN': TOKEN,
            'FILESHAPE_STATE_DIR': str(Path(directory.name) / 'state'),
        })
        env.start()
        self.addCleanup(env.stop)
        rate = patch.object(server, 'RATE_LIMIT_PER_MINUTE', 1000)
        rate.start()
        self.addCleanup(rate.stop)
        server.recent_requests.clear()
        self.auth = {'X-Telegram-Init-Data': signed_init_data(user_id=12345)}

    def create(self, client, key):
        return client.post(
            '/api/v1/jobs', headers={**self.auth, 'Idempotency-Key': key},
            files={'upload': ('input.txt', b'fixture input', 'text/plain')},
            data={'action': 'txt:docx'},
        )

    def wait_terminal(self, client, job_id):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = client.get(f'/api/v1/jobs/{job_id}', headers=self.auth)
            self.assertEqual(response.status_code, 200, response.text)
            status = response.json()['state']
            if status in {'completed', 'failed', 'cancelled'}:
                return status
            time.sleep(0.03)
        self.fail('Job did not reach a terminal state within eight seconds')

    def test_unexpected_sigkill_fails_job_releases_resources_and_next_job_succeeds(self):
        original_worker = server.run_worker
        original_spawn = asyncio.create_subprocess_exec
        children = []
        work_paths = []

        async def killed_process(*_args, **kwargs):
            proc = await original_spawn(
                sys.executable, '-c', 'import os,signal; os.kill(os.getpid(), signal.SIGKILL)', **kwargs,
            )
            children.append(proc)
            return proc

        async def dying_worker(payload, *args, **kwargs):
            if payload['operation'] != 'single':
                return await original_worker(payload, *args, **kwargs)
            work_paths.append(Path(payload['work']))
            with patch('api.worker_runner.asyncio.create_subprocess_exec', side_effect=killed_process):
                return await original_worker(payload, *args, **kwargs)

        with TestClient(server.api) as client:
            with patch.object(server, 'run_worker', side_effect=dying_worker):
                accepted = self.create(client, 'crashed-worker-fixture-key-0001')
                self.assertEqual(accepted.status_code, 202, accepted.text)
                failed_id = accepted.json()['job_id']
                self.assertEqual(self.wait_terminal(client, failed_id), 'failed')
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0].returncode, -signal.SIGKILL)
            self.assertTrue(work_paths)
            self.assertTrue(all(not path.exists() for path in work_paths))
            self.assertEqual(server.background_jobs.artifacts.reserved_bytes, 0)
            self.assertEqual(server.background_jobs.artifacts.count, 0)
            self.assertEqual(server.job_manager.active, 0)
            self.assertEqual(client.get(f'/api/v1/jobs/{failed_id}/result', headers=self.auth).status_code, 404)
            # Use the real parser subprocess again, without restarting the API.
            accepted = self.create(client, 'healthy-worker-fixture-key-0002')
            self.assertEqual(accepted.status_code, 202, accepted.text)
            succeeded_id = accepted.json()['job_id']
            self.assertNotEqual(succeeded_id, failed_id)
            self.assertEqual(self.wait_terminal(client, succeeded_id), 'completed')
            response = client.get(f'/api/v1/jobs/{succeeded_id}/result', headers=self.auth)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.content.startswith(b'PK'))
